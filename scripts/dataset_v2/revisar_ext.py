#!/usr/bin/env python3
"""Aplica a revisão das frases divergentes de `revisao_ext.json` (issue #7).

Critérios usados (registrados aqui para que a revisão seja auditável e refeita):
- Rótulo só vale se o TEXTO o sustenta, sem depender do prompt que o gerou.
- `mulher` exige pista de vítima feminina (presa, sozinha, desesperada, seguida…) ou
  conteúdo de assédio sexual/de gênero. Perseguição ou agressão sem essa pista vai para
  `seguranca` quando a ameaça física é clara, e é descartada quando é vaga (regra provisória, #23).
- Ouvidoria: `risco_potencial` é denúncia de irregularidade (fraude, favorecimento…);
  reclamação, elogio, sugestão e dúvida são `orientacao`.
- Saúde: dor torácica, sangramento forte, falta de ar, alergia com edema e confusão aguda
  são `risco_imediato`; mal-estar sem sinais de alarme é `risco_potencial`.
- Fumaça/fogo/arrombamento/grupo forçando porta/briga em curso: `risco_imediato`.
- Frases ambíguas, vagas ou fora do escopo (perdido no campus, animal ferido) são descartadas.

Decisões por índice da lista original (ordem do arquivo). Entram em `teste_ext.json` com
`origem: ext-ollama-revisado`; as descartadas ficam em `revisao_ext.json` para política futura.
"""
import json
from pathlib import Path

AQUI = Path(__file__).resolve().parent
S, M, H, O = "seguranca", "mulher", "saude", "ouvidoria"
I, P, R = "risco_imediato", "risco_potencial", "orientacao"
X = None  # descartar
D = [
    (S, I), (S, I), (S, P), (S, I), (S, I), (S, I), (S, P), (S, P), (S, P), (S, P),            # 0-9
    X, (S, I), (S, P), X, (S, P), (S, I), (S, P), (S, I), (S, P), X,                           # 10-19
    (S, P), (S, P), (S, I), (S, P), (S, I), (S, R), (S, I), (M, I), (M, I), X,                 # 20-29
    (M, I), (S, P), (M, I), (M, I), X, (M, P), (S, I), X, X, X,                                 # 30-39
    X, X, (M, I), X, (M, I), (M, I), (S, P), (M, P), X, X,                                      # 40-49
    X, X, (S, P), (O, R), (H, I), (H, P), (H, P), (S, I), (H, P), (H, P),                       # 50-59
    X, (H, I), (H, I), (H, P), (H, P), (H, P), X, (H, P), (H, I), (O, R),                       # 60-69
    (O, R), (O, R), (O, R), (O, R), X, (O, R), (O, R), (O, R), X, (O, R),                       # 70-79
    (S, P), X, (M, I), (S, I), X, X, (M, I), (S, P), (M, P), (M, P),                            # 80-89
    (M, P), X, (M, P), (M, P), (M, P), (S, I), (S, P), (S, I), X, (S, I),                       # 90-99
    (M, I), (S, I), (S, I), (S, P), (S, P), X, (O, R), (O, R), (O, R), (O, R),                  # 100-109
    (O, R), (O, R), (O, R), (O, R), (O, P), (O, R), (O, R), (O, R), (O, R), (O, P),             # 110-119
    (O, R), (O, R), (O, R), X, (H, P), (H, R), (H, R), (H, I), (H, P), (H, P),                  # 120-129
    (H, I), (H, P), (H, R), (H, I), (H, P), (H, P), (H, P), (H, R), (M, R), (M, P),             # 130-139
    (O, R), (S, P), X, (S, I), (M, P), (S, P), (O, R), X, (S, P), X,                            # 140-149
    (S, P), X, (S, I), (S, I), (S, P), (S, P), (S, P), (S, P), X, (S, P),                       # 150-159
    (S, P), (S, P), (S, P), (S, I), (S, R), (S, I), (S, P), (S, I), (S, P), (S, P),            # 160-169
    (S, I), (S, P), (S, P), (S, P),                                                             # 170-173
]


def main() -> None:
    rev = json.loads((AQUI / "revisao_ext.json").read_text("utf-8"))
    assert len(rev) == len(D), (len(rev), len(D))
    ok = json.loads((AQUI / "teste_ext.json").read_text("utf-8"))
    ficam = []
    for d, dec in zip(rev, D):
        if dec is None:
            ficam.append(d)
            continue
        tipo, grav = dec
        ok.append({"texto": d["texto"], "tipo": tipo, "gravidade": grav,
                   "origem": "ext-ollama-revisado",
                   "rotulo_gerador": [d["tipo"], d["gravidade"]]})
    (AQUI / "teste_ext.json").write_text(json.dumps(ok, ensure_ascii=False, indent=1), "utf-8")
    (AQUI / "revisao_ext.json").write_text(json.dumps(ficam, ensure_ascii=False, indent=1), "utf-8")
    print(f"aceitas {len(rev) - len(ficam)} · descartadas {len(ficam)} · teste_ext agora {len(ok)}")


if __name__ == "__main__":
    main()
