#!/usr/bin/env python3
"""P.O.T.O — auto-teste MODULAR: exercita cada componente da arquitetura em
ISOLAMENTO e reporta PASS / FAIL / SKIP. Complementa o `doctor.sh` (que checa
presença) exercitando a *função* de cada módulo (rotear, classificar, gravar,
transcrever, sintetizar, notificar, discar).

Uso (rode com o venv do backend):
    cd backend && uv run python ../scripts/selftest.py
    ... --only db,router,agentes      # subconjunto
    ... --json                        # saída para máquina
    ... --simcom                      # inclui teste AT do modem (abre a porta serial)
    ... --audio                       # inclui captura real de mic (arecord 1s)

Isolamento: usa um SQLite temporário (não toca no poto.db real) e o provider de
notificação 'log' (não dispara alerta externo). Cada módulo é independente — a
falha de um não derruba os demais. Degrada com elegância: componente opcional
ausente vira SKIP, não FAIL.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# --- isolamento ANTES de importar o app (config lê env no import) ----------
ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
_tmpdb = tempfile.NamedTemporaryFile(prefix="poto-selftest-", suffix=".db", delete=False)
_tmpdb.close()
os.environ["POTO_DB_PATH"] = _tmpdb.name


class Skip(Exception):
    """Sinaliza componente opcional ausente (vira SKIP, não FAIL)."""


# --- registro de resultados ------------------------------------------------
GREEN, RED, YELLOW, DIM, BOLD, RST = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"
)
_ICON = {"PASS": f"{GREEN}[PASS]{RST}", "FAIL": f"{RED}[FAIL]{RST}", "SKIP": f"{YELLOW}[SKIP]{RST}"}


def _run(nome: str, fn) -> dict:
    t0 = time.perf_counter()
    try:
        detalhe = fn() or ""
        status = "PASS"
    except Skip as e:
        detalhe, status = str(e), "SKIP"
    except Exception as e:  # noqa: BLE001 — cada teste é isolado
        detalhe, status = f"{type(e).__name__}: {e}", "FAIL"
    ms = (time.perf_counter() - t0) * 1000
    return {"modulo": nome, "status": status, "ms": round(ms, 1), "detalhe": detalhe}


# --- testes por módulo -----------------------------------------------------
def t_config() -> str:
    from app import config
    return (f"provider={config.NOTIF_PROVIDER} · ollama={config.OLLAMA_MODEL} · "
            f"stt={os.getenv('POTO_STT_PROVIDER', 'none')}")


def t_db() -> str:
    from app import db
    from app.models import Modo, TipoOcorrencia
    from app.router_engine import rotear
    db.init_db()
    evento = {"evento_id": "self-test-1", "totem_id": "TOTEM-SELFTEST",
              "tipo_ocorrencia": "seguranca", "modo": "normal",
              "origem_acionamento": "touch", "descricao": "", "timestamp_local": ""}
    routing = rotear(TipoOcorrencia.seguranca, Modo.normal)  # shape real esperado pelo db
    ch = db.create_chamado(evento, routing, None)
    lido = db.get_chamado(ch["chamado_id"])
    if not lido or not lido.get("canal_roteado"):
        raise RuntimeError("chamado não persistiu/leu corretamente")
    return f"escreveu+leu chamado {ch['chamado_id']} (canal {lido['canal_roteado']})"


def t_router() -> str:
    from app.models import Modo, TipoOcorrencia
    from app.router_engine import rotear
    casos = [
        (TipoOcorrencia.mulher, Modo.discreto),
        (TipoOcorrencia.saude, Modo.normal),
        (TipoOcorrencia.seguranca, Modo.normal),
        (TipoOcorrencia.ouvidoria, Modo.normal),
    ]
    for tipo, modo in casos:
        r = rotear(tipo, modo)
        canal = r.get("canal_roteado") or r.get("canal")
        if not canal:
            raise RuntimeError(f"rotear({tipo.value},{modo.value}) sem canal: {r}")
    return f"{len(casos)} trilhas roteadas (regra determinística)"


def t_agentes() -> str:
    from app.agents.graph import status_agentes, triagem_conversacional
    from app.models import Modo
    st = status_agentes()
    t0 = time.perf_counter()
    r = triagem_conversacional("um homem está me seguindo perto do bloco 7", Modo.normal)
    dt = time.perf_counter() - t0
    tipo = r.get("tipo_sugerido") or r.get("tipo") or r.get("tipo_ocorrencia")
    if not tipo:
        raise RuntimeError(f"triagem sem tipo: {r}")
    modo_infer = st.get("modo", "?")
    return f"modo={modo_infer} modelo={st.get('modelo')} → tipo={tipo} em {dt*1000:.0f}ms"


def t_stt() -> str:
    from app import stt
    if not stt.disponivel():
        raise Skip(f"POTO_STT_PROVIDER={os.getenv('POTO_STT_PROVIDER', 'none')} — sem STT")
    # WAV de 0,5s de silêncio: valida que o modelo carrega e roda (retorna string).
    import struct
    import wave
    wav = Path(tempfile.gettempdir()) / "poto-selftest-stt.wav"
    with wave.open(str(wav), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(struct.pack("<8000h", *([0] * 8000)))
    txt = stt.transcrever(wav.read_bytes(), sufixo=".wav")
    return f"modelo carregou e transcreveu (saída {len(txt or '')} chars)"


def t_voz() -> str:
    from app import voz
    if not voz.disponivel():
        raise Skip("POTO_VOICE_TTS!=local ou Piper/modelo ausente")
    nome = voz.gerar_audio_local("Teste de locução do P O T O.")
    if not nome:
        raise RuntimeError("Piper não gerou o WAV")
    return f"Piper sintetizou {nome}"


def t_notifier() -> str:
    import asyncio

    from app import db, notifier
    db.init_db()
    orig = notifier.NOTIF_PROVIDER
    notifier.NOTIF_PROVIDER = "log"  # isola: não dispara alerta externo
    try:
        chamado = {"chamado_id": "SELFTEST-NOTIF", "tipo_ocorrencia": "seguranca",
                   "gravidade": "risco_potencial", "totem_id": "TOTEM-SELFTEST",
                   "canal_roteado": "csv"}
        ok, detalhe = asyncio.run(notifier.enviar_para_canal(chamado, "csv"))
        if not ok:
            raise RuntimeError(f"enviar_para_canal falhou: {detalhe}")
        linhas = db.list_notificacoes("SELFTEST-NOTIF")
        return f"despachou via log e registrou {len(linhas)} notificação(ões)"
    finally:
        notifier.NOTIF_PROVIDER = orig


def t_microfone(audio: bool) -> str:
    if not _have("arecord"):
        raise Skip("arecord ausente (instale alsa-utils)")
    n = _count_cards(subprocess.run(["arecord", "-l"], capture_output=True, text=True).stdout)
    if n == 0:
        raise RuntimeError("nenhum dispositivo de captura")
    if audio:
        out = Path(tempfile.gettempdir()) / "poto-selftest-mic.wav"
        subprocess.run(["arecord", "-d", "1", "-f", "cd", str(out)],
                       capture_output=True, timeout=8)
        sz = out.stat().st_size if out.exists() else 0
        return f"{n} dispositivo(s); capturou 1s ({sz} bytes)"
    return f"{n} dispositivo(s) de captura (use --audio p/ gravar 1s)"


def t_classificador() -> str:
    from app import classificador
    if not classificador.disponivel():
        raise Skip("sem sklearn ou modelo treinado (uv sync --extra clf && make train-clf)")
    r = classificador.classificar("estou com dor no peito e sem ar")
    if not r or r["tipo"] != "saude":
        raise RuntimeError(f"classificação inesperada: {r}")
    return f"tipo={r['tipo']} grav={r.get('gravidade')} conf={r['confianca']} (governa a triagem)"


def t_camera() -> str:
    vids = sorted(Path("/dev").glob("video*"))
    if not vids:
        if _have("libcamera-hello") or _have("rpicam-hello"):
            raise Skip("CSI via libcamera (sem /dev/video*)")
        raise Skip("nenhum /dev/video* (câmera ausente/não plugada)")
    if _have("ffmpeg"):
        out = Path(tempfile.gettempdir()) / "poto-selftest-cam.jpg"
        p = subprocess.run(["ffmpeg", "-y", "-f", "v4l2", "-i", str(vids[0]),
                            "-frames:v", "1", str(out)], capture_output=True, timeout=10)
        if out.exists() and out.stat().st_size > 0:
            return f"{vids[0].name}: frame capturado ({out.stat().st_size} bytes)"
        return f"{len(vids)} câmera(s) presentes (captura falhou: {p.returncode})"
    return f"{len(vids)} câmera(s) presente(s) (ffmpeg ausente p/ captura)"


def t_simcom() -> str:
    from app import config
    try:
        import serial  # type: ignore
    except ImportError:
        raise Skip("pyserial ausente (uv sync --extra simcom)")
    porta = config.SIMCOM_PORT
    if not Path(porta).exists():
        raise Skip(f"{porta} ausente (módulo desconectado?)")
    ser = serial.Serial(porta, config.SIMCOM_BAUD, timeout=1)
    try:
        def _at(cmd: str) -> str:
            ser.reset_input_buffer()
            ser.write((cmd + "\r\n").encode())
            time.sleep(0.4)
            return ser.read(256).decode("utf-8", "ignore").strip()
        if "OK" not in _at("AT"):
            raise RuntimeError(f"{porta} não respondeu OK ao AT (ModemManager na porta?)")
        csq = _at("AT+CSQ")
        pin = _at("AT+CPIN?")
        return f"{porta}: AT ok · {csq.replace(chr(10), ' ')} · {pin.replace(chr(10), ' ')}"
    finally:
        ser.close()


# --- utilitários -----------------------------------------------------------
def _have(cmd: str) -> bool:
    return subprocess.run(["which", cmd], capture_output=True).returncode == 0


def _count_cards(saida: str) -> int:
    return sum(1 for ln in saida.splitlines() if ln.startswith("card"))


TESTES = {
    "config": t_config,
    "db": t_db,
    "router": t_router,
    "classificador": t_classificador,
    "agentes": t_agentes,
    "stt": t_stt,
    "voz": t_voz,
    "notifier": t_notifier,
    "camera": t_camera,
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Auto-teste modular do P.O.T.O")
    ap.add_argument("--only", help="lista separada por vírgula (ex.: db,router,agentes)")
    ap.add_argument("--json", action="store_true", help="saída JSON")
    ap.add_argument("--simcom", action="store_true", help="inclui teste AT do modem")
    ap.add_argument("--audio", action="store_true", help="captura 1s real no microfone")
    args = ap.parse_args()

    plano = dict(TESTES)
    plano["microfone"] = lambda: t_microfone(args.audio)
    if args.simcom:
        plano["simcom"] = t_simcom
    if args.only:
        alvo = {m.strip() for m in args.only.split(",")}
        plano = {k: v for k, v in plano.items() if k in alvo}

    resultados = [_run(nome, fn) for nome, fn in plano.items()]
    os.unlink(_tmpdb.name)  # limpa o SQLite temporário

    if args.json:
        print(json.dumps(resultados, ensure_ascii=False, indent=2))
    else:
        print(f"\n{BOLD}P.O.T.O — auto-teste modular{RST}  {DIM}({time.strftime('%d/%m %H:%M')}){RST}\n")
        for r in resultados:
            print(f"  {_ICON[r['status']]} {r['modulo']:<11} {DIM}{r['ms']:>7.1f}ms{RST}  {r['detalhe']}")
        n = {s: sum(1 for r in resultados if r["status"] == s) for s in ("PASS", "FAIL", "SKIP")}
        print(f"\n  {BOLD}{n['PASS']} PASS · {n['FAIL']} FAIL · {n['SKIP']} SKIP{RST}\n")

    sys.exit(1 if any(r["status"] == "FAIL" for r in resultados) else 0)


if __name__ == "__main__":
    main()
