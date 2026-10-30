#!/usr/bin/env python3
"""Amplia o TESTE com frases geradas por LLM local (Ollama), sem gastar tokens de API.

Gerador (gemma3:12b) escreve frases por célula tipo×gravidade com estilos variados;
um verificador independente (qwen3:8b) reclassifica cada frase às cegas. Só entram em
`teste_ext.json` as frases em que o verificador CONCORDA nos dois rótulos; as demais
vão para `revisao_ext.json` para revisão humana. Frases quase iguais às já existentes
(treino/validação/teste) são descartadas para não haver vazamento.

Limitação assumida: frases de LLM são mais "limpas" e previsíveis que as de pessoas;
o conjunto serve para dar poder estatístico, não substitui testes com usuários.

Uso:  python3 gerar_ext_ollama.py [--url http://localhost:11434]
"""

from __future__ import annotations

import argparse
import json
import random
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
GERADOR, VERIFICADOR = "gemma3:12b", "qwen3:8b"

DEF_TIPO = {
    "seguranca": "ameaça, crime, invasão, briga, incêndio, perigo físico ou dúvida sobre a segurança do campus",
    "mulher": "violência, assédio ou importunação sexual/de gênero contra mulher; ou orientação sobre a rede de proteção à mulher",
    "saude": "mal-estar, acidente, emergência clínica, saúde mental, ou dúvida sobre atendimento de saúde",
    "ouvidoria": "reclamação, denúncia de irregularidade administrativa, sugestão, elogio ou dúvida sobre a ouvidoria/Fala.BR",
}
DEF_GRAV = {
    "risco_imediato": "acontecendo AGORA, risco iminente à vida ou integridade; exige ação imediata",
    "risco_potencial": "situação preocupante ou ameaça difusa, sem perigo iminente neste instante",
    "orientacao": "pedido de informação ou orientação; nenhum risco",
}
CELULAS = [(t, g) for t in ("seguranca", "mulher", "saude") for g in DEF_GRAV] + [
    ("ouvidoria", "risco_potencial"), ("ouvidoria", "orientacao")]
ESTILOS = [
    "coloquial, como mensagem de WhatsApp, com gírias do Piauí e sem pontuação perfeita",
    "curta e telegráfica, de quem está em pânico digitando rápido, com possíveis erros de digitação",
    "educada e formal, de servidor ou professor",
    "relato mais longo (duas orações), com local do campus UFPI (bloco, CCS, CT, RU, biblioteca, HU)",
]


def chat(url: str, modelo: str, prompt: str, temp: float, think: bool = False) -> dict:
    corpo = {"model": modelo, "stream": False, "format": "json", "think": think,
             "options": {"temperature": temp, "num_predict": 700},
             "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(f"{url}/api/chat", json.dumps(corpo).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(json.loads(r.read())["message"]["content"])


def trigramas(t: str) -> set[str]:
    t = " ".join(t.lower().split())
    return {t[i:i + 3] for i in range(max(1, len(t) - 2))}


def parecida(a: str, existentes: list[set[str]], lim: float = 0.6) -> bool:
    ta = trigramas(a)
    return any(len(ta & b) / max(1, len(ta | b)) >= lim for b in existentes)


def gerar(url: str, tipo: str, grav: str, estilo: str, n: int = 5) -> list[str]:
    prompt = (
        f"Você escreve exemplos de mensagens enviadas por pessoas a um totem de emergência "
        f"da Universidade Federal do Piauí (UFPI, Teresina), em português do Brasil.\n"
        f"Escreva {n} mensagens DIFERENTES entre si, cada uma de UMA pessoa.\n"
        f"Categoria: {tipo} — {DEF_TIPO[tipo]}.\nGravidade: {grav} — {DEF_GRAV[grav]}.\n"
        f"Estilo: {estilo}.\nNão cite a categoria nem a gravidade no texto. "
        f'Responda só JSON: {{"frases": ["...", "..."]}}')
    out = chat(url, GERADOR, prompt, temp=0.9)
    return [f.strip() for f in out.get("frases", []) if isinstance(f, str) and 8 < len(f.strip()) < 220]


def verificar(url: str, texto: str) -> dict:
    prompt = (
        "Classifique a mensagem enviada a um totem de emergência universitário.\n"
        "tipo: seguranca | mulher | saude | ouvidoria\n"
        + "".join(f"- {k}: {v}\n" for k, v in DEF_TIPO.items())
        + "gravidade: risco_imediato | risco_potencial | orientacao\n"
        + "".join(f"- {k}: {v}\n" for k, v in DEF_GRAV.items())
        + f'\nMensagem: "{texto}"\nResponda só JSON: {{"tipo": "...", "gravidade": "..."}}')
    return chat(url, VERIFICADOR, prompt, temp=0.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:11434")
    ap.add_argument("--chamadas-imediato", type=int, default=6, help="chamadas por célula de risco imediato")
    ap.add_argument("--chamadas", type=int, default=3, help="chamadas por célula (demais)")
    ap.add_argument("--celulas", help="subconjunto, ex.: mulher:risco_imediato,ouvidoria:risco_potencial")
    ap.add_argument("--acrescentar", action="store_true", help="soma aos teste_ext/revisao_ext existentes")
    args = ap.parse_args()
    rng = random.Random(7 + (1 if args.acrescentar else 0))
    celulas = CELULAS if not args.celulas else [tuple(c.split(":")) for c in args.celulas.split(",")]
    prev_ok = prev_rv = []
    if args.acrescentar:
        prev_ok = json.loads((AQUI / "teste_ext.json").read_text("utf-8"))
        prev_rv = json.loads((AQUI / "revisao_ext.json").read_text("utf-8"))

    existentes = []
    for nome in ("treino", "validacao", "teste"):
        existentes += [trigramas(d["texto"]) for d in json.loads((AQUI / f"{nome}.json").read_text("utf-8"))]

    existentes += [trigramas(d["texto"]) for d in prev_ok + prev_rv]
    cand: list[dict] = []
    for tipo, grav in celulas:
        n_calls = args.chamadas_imediato if grav == "risco_imediato" else args.chamadas
        estilos = [ESTILOS[i % len(ESTILOS)] for i in range(n_calls)]
        rng.shuffle(estilos)
        for est in estilos:
            for f in gerar(args.url, tipo, grav, est):
                if not parecida(f, existentes):
                    existentes.append(trigramas(f))
                    cand.append({"texto": f, "tipo": tipo, "gravidade": grav, "origem": "ext-ollama"})
        print(f"{tipo:10s} {grav:16s} acumulado {len(cand)}", flush=True)

    ok, revisao = [], []
    for d in cand:
        try:
            v = verificar(args.url, d["texto"])
        except Exception as e:  # noqa: BLE001
            v = {"erro": str(e)}
        if v.get("tipo") == d["tipo"] and v.get("gravidade") == d["gravidade"]:
            ok.append(d)
        else:
            revisao.append({**d, "verificador": v})
    ok, revisao = prev_ok + ok, prev_rv + revisao
    (AQUI / "teste_ext.json").write_text(json.dumps(ok, ensure_ascii=False, indent=1), "utf-8")
    (AQUI / "revisao_ext.json").write_text(json.dumps(revisao, ensure_ascii=False, indent=1), "utf-8")
    print(f"candidatas {len(cand)} → concordam {len(ok)} (teste_ext) · divergem {len(revisao)} (revisao_ext)")


if __name__ == "__main__":
    main()
