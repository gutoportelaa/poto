"""Camada de persistência (SQLite via stdlib — sem ORM, mínimo de dependências).

Mantém apenas dados estritamente necessários (princípio de minimização da LGPD):
identificação do totem, tipo, gravidade, estados e observação interna breve.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

from .config import DB_PATH, SLA_SEGUNDOS

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
    return d


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


def add_heartbeat(totem_id: str, status: dict) -> None:
    with _lock:
        c = conn()
        c.execute(
            "INSERT INTO heartbeats (totem_id, status_json, created_at) VALUES (?,?,?)",
            (totem_id, json.dumps(status), _now()),
        )
        c.commit()
