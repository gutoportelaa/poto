"""P.O.T.O — API FastAPI.

Camadas: API de Eventos (ingestão idempotente) -> Roteador determinístico ->
Banco de Ocorrências -> Painel (tempo real por WebSocket). Agentes de IA opcionais.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, notifier, sla, stt, video
from .agents.graph import conversa_voz, status_agentes, triagem_conversacional
from .config import FRONTEND_DIST
from .models import (
    ChamadoUpdate,
    ConversaIn,
    ConversaOut,
    EventoIn,
    EventoOut,
    Gravidade,
    HeartbeatIn,
    Modo,
    StatusChamado,
    TriagemIn,
    TriagemOut,
)
from .router_engine import CANAIS, rotear

@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    task = asyncio.create_task(sla.sla_loop(hub))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="P.O.T.O API",
    version="0.1.0",
    description="Plataforma de Orientação, Triagem e Ouvidoria — Totem de Emergência UFPI",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # PoC; restringir no piloto.
    allow_methods=["*"],
    allow_headers=["*"],
)

API = "/api/v1"


# --- WebSocket: broadcast para o painel -----------------------------------
class Hub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, evento: str, dados: dict) -> None:
        msg = json.dumps({"evento": evento, "dados": dados}, ensure_ascii=False)
        dead = []
        for ws in self._clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


hub = Hub()


# --- Sinalização WebRTC: salas (1 por chamado) ----------------------------
class SignalingHub:
    """Relé de SDP/ICE entre pares de uma mesma sala. O vídeo é peer-to-peer;
    o backend só intermedia a negociação."""

    def __init__(self) -> None:
        self._salas: dict[str, set[WebSocket]] = {}

    async def entrar(self, sala: str, ws: WebSocket) -> None:
        await ws.accept()
        self._salas.setdefault(sala, set()).add(ws)

    def sair(self, sala: str, ws: WebSocket) -> None:
        peers = self._salas.get(sala)
        if peers:
            peers.discard(ws)
            if not peers:
                self._salas.pop(sala, None)

    async def rele(self, sala: str, remetente: WebSocket, raw: str) -> None:
        for peer in list(self._salas.get(sala, set())):
            if peer is remetente:
                continue
            try:
                await peer.send_text(raw)
            except Exception:
                self.sair(sala, peer)


rtc = SignalingHub()


@app.get(f"{API}/health")
def health() -> dict:
    return {
        "status": "ok",
        "agentes": status_agentes(),
        "stt": stt.status(),
        "video": video.status(),
        "notificacao": notifier.status(),
    }


@app.get(f"{API}/canais")
def canais() -> dict:
    return CANAIS


# --- API de Eventos (acionamento do totem) --------------------------------
@app.post(f"{API}/eventos", response_model=EventoOut, status_code=201)
async def criar_evento(evento: EventoIn) -> EventoOut:
    # Triagem opcional por agentes quando há texto livre; senão, roteamento direto.
    triagem = None
    emergencia = False
    if evento.texto_livre:
        triagem = triagem_conversacional(evento.texto_livre, evento.modo)
        emergencia = triagem.get("gravidade") == Gravidade.risco_imediato.value

    routing = rotear(evento.tipo_ocorrencia, evento.modo, emergencia=emergencia)
    if triagem and triagem.get("gravidade"):
        routing["gravidade"] = Gravidade(triagem["gravidade"])

    chamado = db.create_chamado(evento.model_dump(mode="json"), routing, triagem)
    duplicado = chamado.pop("_duplicado", False)

    if not duplicado:
        await hub.broadcast("novo_chamado", chamado)
        _, chamado = await notifier.notificar_chamado(chamado)
        await hub.broadcast("atualizado", chamado)

    return EventoOut(
        chamado_id=chamado["chamado_id"],
        status=StatusChamado(chamado["status"]),
        canal_roteado=chamado["canal_roteado"],
        gravidade=Gravidade(chamado["gravidade"]),
        instrucao_totem=routing["instrucao"],
        duplicado=duplicado,
    )


# --- Triagem conversacional (agentes) -------------------------------------
@app.post(f"{API}/triagem", response_model=TriagemOut)
def triagem(req: TriagemIn) -> TriagemOut:
    return TriagemOut(**triagem_conversacional(req.texto, req.modo))


@app.post(f"{API}/conversa", response_model=ConversaOut)
def conversa(req: ConversaIn) -> ConversaOut:
    """Triagem conversacional por voz (multi-turno): próxima fala + conclusão."""
    historico = [t.model_dump() for t in req.historico]
    return ConversaOut(**conversa_voz(historico, req.modo))


# --- Recepção de áudio (STT) ----------------------------------------------
@app.post(f"{API}/transcrever")
async def transcrever(audio: UploadFile = File(...)) -> dict:
    dados = await audio.read()
    tamanho = len(dados)
    if not stt.disponivel():
        # Áudio recebido, mas sem provedor de transcrição: a UI mostra "concluído"
        # e pede texto digitado. Não é erro — é indisponibilidade controlada.
        return {
            "texto": "",
            "transcricao_disponivel": False,
            "tamanho_bytes": tamanho,
            "detalhe": "Transcrição automática indisponível (configure POTO_STT_PROVIDER).",
        }
    try:
        sufixo = "." + ((audio.filename or "fala.webm").rsplit(".", 1)[-1])
        texto = stt.transcrever(dados, sufixo=sufixo)
        return {"texto": texto, "transcricao_disponivel": True, "tamanho_bytes": tamanho}
    except Exception as e:  # falha real de transcrição -> erro para a UI
        raise HTTPException(503, f"Falha na transcrição: {e}")


# --- Vídeo: registro (evidência) e transmissão (WebRTC) -------------------
@app.get(f"{API}/rtc/config")
def rtc_config() -> dict:
    """Servidores ICE para o WebRTC (consumido pelo totem e pela central)."""
    return {"iceServers": video.ice_servers()}


@app.post(f"{API}/evidencia")
async def evidencia(
    video_file: UploadFile = File(..., alias="video"),
    chamado_id: str = Form("sem-chamado"),
    totem_id: str = Form("TOTEM-CCS-01"),
) -> dict:
    dados = await video_file.read()
    sufixo = "." + ((video_file.filename or "evidencia.webm").rsplit(".", 1)[-1])
    try:
        meta = video.salvar_evidencia(dados, chamado_id, totem_id, sufixo=sufixo)
    except video.EvidenciaDesativada as e:
        raise HTTPException(403, str(e))
    await hub.broadcast("evidencia", meta)
    return meta


@app.get(f"{API}/evidencias")
def evidencias() -> list[dict]:
    return video.listar_evidencias()


@app.websocket(f"{API}/rtc/{{sala}}")
async def rtc_ws(ws: WebSocket, sala: str) -> None:
    """Canal de sinalização. Mensagens trafegam cruas entre os pares da sala;
    'publicando' avisa a central (painel) que há vídeo ativo para o chamado."""
    await rtc.entrar(sala, ws)
    try:
        await rtc.rele(sala, ws, json.dumps({"tipo": "peer-entrou"}))
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("tipo") == "publicando":
                await hub.broadcast(
                    "video_ativo",
                    {"chamado_id": sala, "totem_id": msg.get("totem_id")},
                )
            await rtc.rele(sala, ws, raw)
    except WebSocketDisconnect:
        rtc.sair(sala, ws)
        await rtc.rele(sala, ws, json.dumps({"tipo": "peer-saiu"}))
    except Exception:
        rtc.sair(sala, ws)


# --- Heartbeat ------------------------------------------------------------
@app.post(f"{API}/totens/{{totem_id}}/heartbeat")
async def heartbeat(totem_id: str, hb: HeartbeatIn) -> dict:
    db.add_heartbeat(totem_id, hb.model_dump())
    await hub.broadcast("heartbeat", {"totem_id": totem_id, **hb.model_dump()})
    return {"ok": True}


# --- Painel ---------------------------------------------------------------
@app.get(f"{API}/chamados")
def listar(tipo: str | None = None, status: str | None = None, gravidade: str | None = None):
    return db.list_chamados(tipo, status, gravidade)


@app.get(f"{API}/chamados/{{chamado_id}}")
def detalhe(chamado_id: str):
    c = db.get_chamado(chamado_id)
    if not c:
        raise HTTPException(404, "Chamado não encontrado")
    c["notificacoes"] = db.list_notificacoes(chamado_id)
    return c


@app.post(f"{API}/chamados/{{chamado_id}}/ack")
async def ack(chamado_id: str):
    c = db.ack_chamado(chamado_id)
    if not c:
        raise HTTPException(404, "Chamado não encontrado")
    await hub.broadcast("atualizado", c)
    return c


@app.patch(f"{API}/chamados/{{chamado_id}}")
async def atualizar(chamado_id: str, upd: ChamadoUpdate):
    c = db.update_chamado(
        chamado_id,
        status=upd.status.value if upd.status else None,
        observacao=upd.observacao,
    )
    if not c:
        raise HTTPException(404, "Chamado não encontrado")
    await hub.broadcast("atualizado", c)
    return c


@app.websocket(f"{API}/ws")
async def ws(ws: WebSocket) -> None:
    await hub.connect(ws)
    try:
        await ws.send_text(json.dumps({"evento": "conectado", "dados": status_agentes()}))
        while True:
            await asyncio.sleep(30)
            await ws.send_text(json.dumps({"evento": "ping", "dados": {}}))
    except WebSocketDisconnect:
        hub.disconnect(ws)
    except Exception:
        hub.disconnect(ws)


# --- Frontend estático (modo standalone: backend serve a PWA) -------------
_dist = Path(FRONTEND_DIST)
if _dist.is_dir():
    app.mount("/app", StaticFiles(directory=str(_dist), html=True), name="app")


@app.get("/")
def raiz() -> JSONResponse:
    return JSONResponse(
        {
            "servico": "P.O.T.O API",
            "docs": "/docs",
            "health": f"{API}/health",
            "painel_pwa": "/app/painel.html" if _dist.is_dir() else "rode o frontend (bun)",
        }
    )
