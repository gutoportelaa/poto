"""Camada de persistência (SQLite via stdlib — sem ORM, mínimo de dependências).

Mantém apenas dados estritamente necessários (princípio de minimização da LGPD):
identificação do totem, tipo, gravidade, estados e observação interna breve.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

from .config import DB_PATH, SLA_SEGUNDOS, TOTEM_OFFLINE_SEG

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


def init_db() -> None:
    with _lock:
        c = conn()
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS chamados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chamado_id TEXT UNIQUE,
                evento_id TEXT UNIQUE,
                totem_id TEXT NOT NULL,
                tipo_ocorrencia TEXT NOT NULL,
                modo TEXT NOT NULL,
                origem_acionamento TEXT,
                gravidade TEXT NOT NULL,
                canal_roteado TEXT NOT NULL,
                fallback TEXT,
                status TEXT NOT NULL,
                observacao TEXT,
                triagem_json TEXT,
                timestamp_local TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                acked_at TEXT
            );
            CREATE TABLE IF NOT EXISTS estado_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chamado_id TEXT NOT NULL,
                de TEXT, para TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS heartbeats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                totem_id TEXT NOT NULL, status_json TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notificacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chamado_id TEXT NOT NULL,
                canal TEXT NOT NULL,
                destino TEXT NOT NULL,
                provider TEXT NOT NULL,
                sucesso INTEGER NOT NULL,
                mensagem TEXT,
                detalhe TEXT,
                escalonamento INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversa_eventos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                totem_id TEXT NOT NULL,
                motivo TEXT NOT NULL,
                turnos INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )
        c.commit()


def _parse_ts(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def add_notificacao(
    chamado_id: str,
    canal: str,
    destino: str,
    provider: str,
    sucesso: bool,
    mensagem: str,
    *,
    detalhe: str | None = None,
    escalonamento: bool = False,
) -> None:
    with _lock:
        c = conn()
        c.execute(
            """INSERT INTO notificacoes
               (chamado_id, canal, destino, provider, sucesso, mensagem, detalhe,
                escalonamento, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                chamado_id, canal, destino, provider, int(sucesso), mensagem,
                detalhe, int(escalonamento), _now(),
            ),
        )
        c.commit()


def add_conversa_evento(totem_id: str, motivo: str, turnos: int = 0) -> None:
    """Loga o abandono de uma conversa de atendimento (desistência manual ou
    inatividade de 10 min). Sem o conteúdo da conversa — só motivo e volume."""
    with _lock:
        c = conn()
        c.execute(
            "INSERT INTO conversa_eventos (totem_id, motivo, turnos, created_at) "
            "VALUES (?,?,?,?)",
            (totem_id, motivo, int(turnos), _now()),
        )
        c.commit()


def list_notificacoes(chamado_id: str) -> list[dict]:
    with _lock:
        rows = conn().execute(
            "SELECT * FROM notificacoes WHERE chamado_id = ? ORDER BY created_at DESC",
            (chamado_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def foi_escalonado(chamado_id: str) -> bool:
    with _lock:
        r = conn().execute(
            "SELECT 1 FROM estado_log WHERE chamado_id = ? AND para = 'escalonado' LIMIT 1",
            (chamado_id,),
        ).fetchone()
    return r is not None


def chamados_sla_expirado() -> list[dict]:
    """Chamados notificados sem ACK dentro do SLA e ainda não escalonados."""
    with _lock:
        rows = conn().execute(
            """SELECT c.* FROM chamados c
               WHERE c.status = 'notificado'
                 AND c.acked_at IS NULL
                 AND c.gravidade IN ('risco_imediato', 'risco_potencial')
                 AND NOT EXISTS (
                   SELECT 1 FROM estado_log e
                   WHERE e.chamado_id = c.chamado_id AND e.para = 'escalonado'
                 )
               ORDER BY c.created_at ASC"""
        ).fetchall()
        candidatos = [row_to_dict(r) for r in rows]
    agora = datetime.now(timezone.utc)
    expirados: list[dict] = []
    for chamado in candidatos:
        sla = SLA_SEGUNDOS.get(chamado["gravidade"])
        if not sla:
            continue
        ref = _parse_ts(chamado["updated_at"])
        if (agora - ref).total_seconds() >= sla:
            expirados.append(chamado)
    return expirados


def row_to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    if d.get("triagem_json"):
        try:
            d["triagem"] = json.loads(d["triagem_json"])
        except json.JSONDecodeError:
            d["triagem"] = None
    d.pop("triagem_json", None)
    # Destaque de emergência (auditoria/painel): risco imediato ou pânico.
    d["emergencia"] = (
        d.get("gravidade") == "risco_imediato"
        or d.get("origem_acionamento") == "panico"
    )
    return d


def list_estado_log(chamado_id: str) -> list[dict]:
    """Linha do tempo de estados, com a duração de cada estado (segundos).
    O último estado fica 'em_curso' e sua duração é medida até agora."""
    with _lock:
        rows = conn().execute(
            "SELECT de, para, created_at FROM estado_log WHERE chamado_id = ? "
            "ORDER BY created_at ASC, id ASC",
            (chamado_id,),
        ).fetchall()
    eventos = [dict(r) for r in rows]
    agora = datetime.now(timezone.utc)
    for i, e in enumerate(eventos):
        ini = _parse_ts(e["created_at"])
        ultimo = i + 1 == len(eventos)
        fim = agora if ultimo else _parse_ts(eventos[i + 1]["created_at"])
        e["duracao_segundos"] = round((fim - ini).total_seconds(), 3)
        e["em_curso"] = ultimo
    return eventos


def tempos_chamado(chamado_id: str) -> dict:
    """Tempos agregados para auditoria: total em aberto e tempo até o ACK."""
    c = get_chamado(chamado_id)
    if not c:
        return {}
    created = _parse_ts(c["created_at"])
    agora = datetime.now(timezone.utc)
    ate_ack = None
    if c.get("acked_at"):
        ate_ack = round((_parse_ts(c["acked_at"]) - created).total_seconds(), 3)
    return {
        "tempo_total_segundos": round((agora - created).total_seconds(), 3),
        "tempo_ate_ack_segundos": ate_ack,
    }


def get_by_evento(evento_id: str) -> dict | None:
    with _lock:
        r = conn().execute(
            "SELECT * FROM chamados WHERE evento_id = ?", (evento_id,)
        ).fetchone()
    return row_to_dict(r) if r else None


def create_chamado(evento: dict, routing: dict, triagem: dict | None) -> dict:
    """Cria o chamado de forma idempotente. Se o evento_id já existe, retorna o existente."""
    existing = get_by_evento(evento["evento_id"])
    if existing:
        existing["_duplicado"] = True
        return existing

    now = _now()
    with _lock:
        c = conn()
        cur = c.execute(
            """INSERT INTO chamados
               (evento_id, totem_id, tipo_ocorrencia, modo, origem_acionamento,
                gravidade, canal_roteado, fallback, status, triagem_json,
                timestamp_local, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                evento["evento_id"], evento["totem_id"], evento["tipo_ocorrencia"],
                evento["modo"], evento.get("origem_acionamento"),
                routing["gravidade"].value, routing["canal_roteado"], routing["fallback"],
                "roteado", json.dumps(triagem) if triagem else None,
                evento.get("timestamp_local"), now, now,
            ),
        )
        rowid = cur.lastrowid
        ano = datetime.now(timezone.utc).year
        chamado_id = f"CALL-{ano}-{rowid:06d}"
        c.execute("UPDATE chamados SET chamado_id = ? WHERE id = ?", (chamado_id, rowid))
        c.execute(
            "INSERT INTO estado_log (chamado_id, de, para, created_at) VALUES (?,?,?,?)",
            (chamado_id, None, "roteado", now),
        )
        c.commit()
        r = c.execute("SELECT * FROM chamados WHERE id = ?", (rowid,)).fetchone()
    out = row_to_dict(r)
    out["_duplicado"] = False
    return out


def list_chamados(
    tipo: str | None = None, status: str | None = None, gravidade: str | None = None
) -> list[dict]:
    q = "SELECT * FROM chamados WHERE 1=1"
    params: list = []
    if tipo:
        q += " AND tipo_ocorrencia = ?"; params.append(tipo)
    if status:
        q += " AND status = ?"; params.append(status)
    if gravidade:
        q += " AND gravidade = ?"; params.append(gravidade)
    q += " ORDER BY created_at DESC LIMIT 200"
    with _lock:
        rows = conn().execute(q, params).fetchall()
    return [row_to_dict(r) for r in rows]


def get_chamado(chamado_id: str) -> dict | None:
    with _lock:
        r = conn().execute(
            "SELECT * FROM chamados WHERE chamado_id = ?", (chamado_id,)
        ).fetchone()
    return row_to_dict(r) if r else None


def update_chamado(
    chamado_id: str, status: str | None = None, observacao: str | None = None
) -> dict | None:
    atual = get_chamado(chamado_id)
    if not atual:
        return None
    now = _now()
    with _lock:
        c = conn()
        if status and status != atual["status"]:
            c.execute(
                "INSERT INTO estado_log (chamado_id, de, para, created_at) VALUES (?,?,?,?)",
                (chamado_id, atual["status"], status, now),
            )
        c.execute(
            "UPDATE chamados SET status = COALESCE(?, status), "
            "observacao = COALESCE(?, observacao), updated_at = ? WHERE chamado_id = ?",
            (status, observacao, now, chamado_id),
        )
        c.commit()
    return get_chamado(chamado_id)


def ack_chamado(chamado_id: str) -> dict | None:
    atual = get_chamado(chamado_id)
    if not atual:
        return None
    now = _now()
    with _lock:
        c = conn()
        c.execute(
            "INSERT INTO estado_log (chamado_id, de, para, created_at) VALUES (?,?,?,?)",
            (chamado_id, atual["status"], "reconhecido", now),
        )
        c.execute(
            "UPDATE chamados SET status='reconhecido', acked_at=?, updated_at=? "
            "WHERE chamado_id=?",
            (now, now, chamado_id),
        )
        c.commit()
    return get_chamado(chamado_id)


def metricas() -> dict:
    """Agregações para a tela de Análises: volumes, tempos e SLA. Tudo derivado
    das tabelas existentes (chamados, notificacoes), sem dados sensíveis."""
    with _lock:
        c = conn()
        total = c.execute("SELECT COUNT(*) n FROM chamados").fetchone()["n"]
        por_gravidade = {r["gravidade"]: r["n"] for r in c.execute(
            "SELECT gravidade, COUNT(*) n FROM chamados GROUP BY gravidade")}
        por_tipo = {r["tipo_ocorrencia"]: r["n"] for r in c.execute(
            "SELECT tipo_ocorrencia, COUNT(*) n FROM chamados GROUP BY tipo_ocorrencia")}
        por_status = {r["status"]: r["n"] for r in c.execute(
            "SELECT status, COUNT(*) n FROM chamados GROUP BY status")}
        ack_med = c.execute(
            "SELECT AVG((julianday(acked_at)-julianday(created_at))*86400) s "
            "FROM chamados WHERE acked_at IS NOT NULL").fetchone()["s"]
        acked = c.execute(
            "SELECT gravidade, created_at, acked_at FROM chamados WHERE acked_at IS NOT NULL").fetchall()
        notif_total = c.execute("SELECT COUNT(*) n FROM notificacoes").fetchone()["n"]
        escal_chamados = c.execute(
            "SELECT COUNT(DISTINCT chamado_id) n FROM notificacoes WHERE escalonamento=1").fetchone()["n"]
        vol = c.execute(
            "SELECT substr(created_at,1,10) dia, COUNT(*) n FROM chamados "
            "GROUP BY dia ORDER BY dia DESC LIMIT 7").fetchall()
        top = c.execute(
            "SELECT totem_id, COUNT(*) n FROM chamados GROUP BY totem_id ORDER BY n DESC LIMIT 5").fetchall()

    # SLA cumprido: % de reconhecidos dentro do prazo (só gravidades com SLA).
    considerados = cumpridos = 0
    for r in acked:
        sla = SLA_SEGUNDOS.get(r["gravidade"])
        if not sla:
            continue
        considerados += 1
        if (_parse_ts(r["acked_at"]) - _parse_ts(r["created_at"])).total_seconds() <= sla:
            cumpridos += 1

    abertos = total - sum(por_status.get(s, 0) for s in ("encerrado", "cancelado"))
    return {
        "total": total,
        "abertos": abertos,
        "emergencias": por_gravidade.get("risco_imediato", 0),
        "por_gravidade": por_gravidade,
        "por_tipo": por_tipo,
        "por_status": por_status,
        "tempo_medio_ack_segundos": round(ack_med, 1) if ack_med is not None else None,
        "sla_cumprido_pct": round(100 * cumpridos / considerados, 1) if considerados else None,
        "contatos_acionados": notif_total,
        "chamados_escalonados": escal_chamados,
        "taxa_escalonamento_pct": round(100 * escal_chamados / total, 1) if total else 0.0,
        "volume_por_dia": [{"dia": r["dia"], "total": r["n"]} for r in reversed(vol)],
        "top_totens": [{"totem_id": r["totem_id"], "total": r["n"]} for r in top],
    }


def list_totens() -> list[dict]:
    """Status agregado por totem para o painel de frota: último heartbeat
    (online/bateria/conectividade/tamper) + atividade (nº de chamados). O campo
    `online` é derivado da recência do heartbeat (TOTEM_OFFLINE_SEG). Inclui
    também totens vistos só em chamados (aparecem como offline/sem telemetria)."""
    agora = datetime.now(timezone.utc)
    with _lock:
        c = conn()
        hb_rows = c.execute(
            """SELECT h.totem_id, h.status_json, h.created_at FROM heartbeats h
               JOIN (SELECT totem_id, MAX(created_at) mc FROM heartbeats GROUP BY totem_id) m
                 ON h.totem_id = m.totem_id AND h.created_at = m.mc"""
        ).fetchall()
        ch_rows = c.execute(
            "SELECT totem_id, COUNT(*) n, MAX(created_at) last FROM chamados GROUP BY totem_id"
        ).fetchall()
    hb = {r["totem_id"]: r for r in hb_rows}
    ch = {r["totem_id"]: r for r in ch_rows}

    totens: list[dict] = []
    for tid in set(hb) | set(ch):
        h = hb.get(tid)
        status: dict = {}
        ultimo = visto = None
        online = False
        if h:
            try:
                status = json.loads(h["status_json"] or "{}")
            except json.JSONDecodeError:
                status = {}
            ultimo = h["created_at"]
            visto = round((agora - _parse_ts(ultimo)).total_seconds(), 1)
            online = bool(status.get("online", True)) and visto <= TOTEM_OFFLINE_SEG
        cinfo = ch.get(tid)
        totens.append({
            "totem_id": tid,
            "online": online,
            "visto_ha_segundos": visto,
            "ultimo_heartbeat": ultimo,
            "bateria": status.get("bateria"),
            "conectividade": status.get("conectividade"),
            "tamper": bool(status.get("tamper", False)),
            "chamados_total": cinfo["n"] if cinfo else 0,
            "ultimo_chamado": cinfo["last"] if cinfo else None,
        })
    # Problemas no topo: tamper, depois offline, depois ordem alfabética.
    totens.sort(key=lambda t: (not t["tamper"], t["online"], t["totem_id"]))
    return totens


def add_heartbeat(totem_id: str, status: dict) -> None:
    with _lock:
        c = conn()
        c.execute(
            "INSERT INTO heartbeats (totem_id, status_json, created_at) VALUES (?,?,?)",
            (totem_id, json.dumps(status), _now()),
        )
        c.commit()
