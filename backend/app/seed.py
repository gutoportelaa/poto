"""Popula o banco com chamados de exemplo para demonstrar o painel."""

from __future__ import annotations

import uuid

from . import db
from .models import Modo, TipoOcorrencia
from .router_engine import rotear

EXEMPLOS = [
    (TipoOcorrencia.seguranca, Modo.normal, None),
    (TipoOcorrencia.mulher, Modo.discreto, None),
    (TipoOcorrencia.saude, Modo.normal, "uma pessoa desmaiou perto da biblioteca"),
    (TipoOcorrencia.ouvidoria, Modo.normal, None),
]


def run() -> None:
    db.init_db()
    for tipo, modo, texto in EXEMPLOS:
        evento = {
            "evento_id": str(uuid.uuid4()),
            "totem_id": "TOTEM-CCS-01",
            "tipo_ocorrencia": tipo.value,
            "modo": modo.value,
            "origem_acionamento": "touch",
            "timestamp_local": None,
        }
        routing = rotear(tipo, modo, emergencia=bool(texto and "desmaiou" in texto))
        db.create_chamado(evento, routing, None)
    print(f"Seed concluído: {len(EXEMPLOS)} chamados criados.")


if __name__ == "__main__":
    run()
