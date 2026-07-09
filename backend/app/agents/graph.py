"""Pipeline de agentes de triagem e conversação.

Orquestração com LangGraph; modelo local via Ollama. Nós:
    conversa -> triagem -> guardrails -> roteamento

Princípio de projeto: TUDO degrada com elegância. Se LangGraph ou Ollama não
estiverem disponíveis, o pipeline usa uma heurística determinística por palavras-chave.
O encaminhamento crítico continua garantido pelo router_engine (independente da IA).
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import TypedDict

from ..config import (
    AGENTS_ENABLED,
    CONVERSA_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
    TRIAGEM_MODEL,
)
from .. import classificador
from ..models import Gravidade, Modo, TipoOcorrencia
from ..router_engine import rotear

# --- Detecção de disponibilidade do stack de IA --------------------------
LANGGRAPH_OK = False
_llms: dict = {}  # cache de ChatOllama por nome de modelo (triagem/conversa/bench)
try:  # pragma: no cover - depende do ambiente
    from langgraph.graph import END, StateGraph
    from langchain_ollama import ChatOllama

    LANGGRAPH_OK = True
except Exception:  # ImportError ou conflito de versões
    StateGraph = None  # type: ignore
    END = None  # type: ignore
    ChatOllama = None  # type: ignore


# --- Heurística de fallback (determinística) ------------------------------
PALAVRAS = {
    TipoOcorrencia.mulher: [
        "assédio", "assedio", "estupro", "ex-namorado", "ex namorado", "marido",
        "perseguindo", "perseguir", "me persegue", "seguindo", "me seguindo", "me segue",
        "me bateu", "violência", "violencia", "importunação", "importunacao",
        "abusou", "abuso", "cantada",
    ],
    TipoOcorrencia.seguranca: [
        "roubo", "assalto", "ladrão", "ladrao", "arma", "briga", "agressão",
        "agressao", "invasão", "invasao", "perigo", "suspeito", "furto", "ameaça",
        "ameaca",
    ],
    TipoOcorrencia.saude: [
        "passando mal", "desmaio", "desmaiou", "convulsão", "convulsao", "dor no peito",
        "sangrando", "ansiedade", "pânico", "panico", "depress", "suicíd", "suicid",
        "me matar", "remédio", "remedio",
    ],
    TipoOcorrencia.ouvidoria: [
        "reclamação", "reclamacao", "denúncia", "denuncia", "sugestão", "sugestao",
        "elogio", "informação", "informacao",
    ],
}
SINAIS_CRITICOS = [
    "suicíd", "suicid", "me matar", "tirar minha vida", "arma", "sangrando",
    "não respira", "nao respira", "desmaiou", "convulsão", "convulsao", "estupro",
]
SINAIS_EMERGENCIA_SAUDE = [
    "desmaio", "desmaiou", "convulsão", "convulsao", "dor no peito", "não respira",
    "nao respira", "sangrando", "suicíd", "suicid", "me matar",
]
# Sinais de ameaça/medo sem categoria clara — nunca caem em "orientação".
SINAIS_AMEACA = [
    "medo", "seguindo", "me seguindo", "atrás de mim", "atras de mim", "sozinha",
    "sozinho", "estranho", "me siga", "fugindo", "escondida", "escondido",
]


def _heuristica(texto: str, modo: Modo) -> dict:
    t = (texto or "").lower()
    pontuacao = {tipo: sum(1 for p in palavras if p in t) for tipo, palavras in PALAVRAS.items()}
    tipo = max(pontuacao, key=pontuacao.get)
    if pontuacao[tipo] == 0:
        # Sem categoria clara: se há sinal de ameaça/medo, trata como segurança
        # (protetivo, 24/7); senão, orientação/ouvidoria.
        tipo = (
            TipoOcorrencia.seguranca
            if any(s in t for s in SINAIS_AMEACA)
            else TipoOcorrencia.ouvidoria
        )
    critico = any(s in t for s in SINAIS_CRITICOS)
    emergencia = any(s in t for s in SINAIS_EMERGENCIA_SAUDE)

    r = rotear(tipo, modo, emergencia=emergencia)
    gravidade = Gravidade.risco_imediato if critico else r["gravidade"]
    confianca = min(0.4 + 0.2 * pontuacao[tipo], 0.85) if pontuacao[tipo] else 0.3
    return {
        "tipo_sugerido": tipo.value,
        "gravidade": gravidade.value,
        "confianca": round(confianca, 2),
        "mensagem_acolhimento": _acolhimento(tipo, modo),
        "canal_sugerido": r["canal_roteado"],
        "escalonar_humano": critico,
        "fonte": "heuristica",
        "nivel": _nivel(gravidade.value, confianca, critico),
    }


# Confiança mínima para o "normal" andar sozinho — abaixo disso, mesmo uma
# triagem de baixo risco pede validação humana (nível "suposto").
CONFIANCA_MIN_AUTONOMA = 0.6


def _nivel(gravidade: str, confianca: float, escalonar_humano: bool) -> str:
    """3 regimes de autonomia (validação humana):
    claro   -> risco_imediato/sinal crítico: aciona já, humano acompanha (não é gate).
    suposto -> risco_potencial ou confiança baixa: aguarda validação humana com SLA.
    normal  -> orientação com confiança alta: bot conduz e encaminha sozinho.
    """
    if escalonar_humano or gravidade == Gravidade.risco_imediato.value:
        return "claro"
    if gravidade == Gravidade.risco_potencial.value or confianca < CONFIANCA_MIN_AUTONOMA:
        return "suposto"
    return "normal"


def _acolhimento(tipo: TipoOcorrencia, modo: Modo) -> str:
    if modo == Modo.discreto or tipo == TipoOcorrencia.mulher:
        return "Estou com você. Seu pedido é sigiloso e já está sendo encaminhado."
    base = {
        TipoOcorrencia.seguranca: "Entendi. Estou acionando a segurança do campus agora.",
        TipoOcorrencia.saude: "Tudo bem, você não está sozinho. Vamos buscar apoio para você.",
        TipoOcorrencia.ouvidoria: "Certo. Vou registrar e orientar o melhor caminho.",
    }
    return base.get(tipo, "Recebi seu pedido. Você está sendo encaminhado.")


# --- Pipeline LangGraph ---------------------------------------------------
class _Estado(TypedDict, total=False):
    texto: str
    modo: str
    tipo: str
    gravidade: str
    confianca: float
    mensagem_acolhimento: str
    canal_sugerido: str
    escalonar_humano: bool


def _chat(model: str | None = None, fmt: str | None = None) -> "ChatOllama | None":
    """ChatOllama por (modelo, formato) com cache. `fmt="json"` força o Ollama a
    devolver JSON válido — decisivo para a robustez dos modelos nano na triagem.
    `model=None` usa o padrão global."""
    if not LANGGRAPH_OK:
        return None
    m = model or OLLAMA_MODEL
    chave = (m, fmt)
    llm = _llms.get(chave)
    if llm is None:
        kwargs = {"model": m, "base_url": OLLAMA_BASE_URL, "temperature": 0,
                  "num_predict": 200, "timeout": OLLAMA_TIMEOUT}
        if fmt:
            kwargs["format"] = fmt
        llm = ChatOllama(**kwargs)
        _llms[chave] = llm
    return llm


def _parse_json(raw: str) -> dict | None:
    """Extrai o primeiro objeto JSON da resposta, tolerando cercas markdown
    (```json), texto ao redor e aspas simples ocasionais dos modelos pequenos."""
    if not raw:
        return None
    txt = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    if not m:
        return None
    bloco = m.group(0)
    for tentativa in (bloco, bloco.replace("'", '"')):
        try:
            return json.loads(tentativa)
        except json.JSONDecodeError:
            continue
    return None


def _node_conversa(state: _Estado) -> _Estado:
    modo = Modo(state.get("modo", "normal"))
    llm = _chat(CONVERSA_MODEL)  # conversa roda sempre local (offline total)
    if llm is None:
        return state
    prompt = (
        "Você é o agente de acolhimento de um totem de emergência universitário. "
        "Responda em português, em UMA frase curta, acolhedora e calma, sem dar "
        "instrução clínica ou jurídica. "
        + ("Use tom neutro e discreto (a pessoa pode estar em risco perto do agressor). "
           if modo == Modo.discreto else "")
        + f'Mensagem da pessoa: "{state.get("texto", "")}"'
    )
    try:
        state["mensagem_acolhimento"] = llm.invoke(prompt).content.strip()[:240]
    except Exception:
        pass
    return state


# Prompt de triagem com few-shot: exemplos ancoram os modelos nano (0.5–2B) a
# devolver o rótulo e o JSON certos. Os exemplos NÃO se sobrepõem ao bench_dataset
# (evita vazamento). Contém chaves JSON literais — concatenado, nunca .format().
_PROMPT_TRIAGEM_PREFIXO = (
    "Você classifica mensagens de um totem de emergência universitário. "
    "Responda SOMENTE um objeto JSON com as chaves tipo, gravidade, confianca.\n"
    "- tipo: seguranca | mulher | saude | ouvidoria\n"
    "- gravidade: risco_imediato | risco_potencial | orientacao\n"
    "- confianca: número de 0.0 a 1.0\n"
    "Regra: mulher = violência/assédio de gênero; seguranca = ameaça/furto/geral; "
    "saude = mal-estar/emergência clínica; ouvidoria = reclamação/sugestão/elogio.\n\n"
    'Mensagem: "vi uma pessoa quebrando as janelas do laboratório"\n'
    '{"tipo":"seguranca","gravidade":"risco_potencial","confianca":0.8}\n'
    'Mensagem: "meu namorado me bateu e está me esperando na saída"\n'
    '{"tipo":"mulher","gravidade":"risco_imediato","confianca":0.95}\n'
    'Mensagem: "estou com muita falta de ar e dor no peito"\n'
    '{"tipo":"saude","gravidade":"risco_imediato","confianca":0.9}\n'
    'Mensagem: "gostaria de sugerir mais bancos no pátio"\n'
    '{"tipo":"ouvidoria","gravidade":"orientacao","confianca":0.7}\n\n'
    "Mensagem: "
)


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


# Sinônimos comuns que os modelos pequenos devolvem, mapeados para os rótulos.
_TIPO_ALIAS = {
    "seguranca": "seguranca", "violencia": "seguranca", "assalto": "seguranca",
    "furto": "seguranca", "roubo": "seguranca", "ameaca": "seguranca",
    "mulher": "mulher", "genero": "mulher", "assedio": "mulher", "violencia_mulher": "mulher",
    "saude": "saude", "medico": "saude", "emergencia_medica": "saude", "clinica": "saude",
    "ouvidoria": "ouvidoria", "reclamacao": "ouvidoria", "denuncia": "ouvidoria",
    "sugestao": "ouvidoria", "elogio": "ouvidoria",
}
_GRAV_ALIAS = {
    "risco_imediato": "risco_imediato", "imediato": "risco_imediato", "alta": "risco_imediato",
    "alto": "risco_imediato", "critico": "risco_imediato", "emergencia": "risco_imediato",
    "risco_potencial": "risco_potencial", "potencial": "risco_potencial", "media": "risco_potencial",
    "medio": "risco_potencial", "moderado": "risco_potencial",
    "orientacao": "orientacao", "baixa": "orientacao", "baixo": "orientacao",
    "informacao": "orientacao", "duvida": "orientacao",
}


def _norm(valor, alias: dict, validos) -> str | None:
    """Normaliza o rótulo do modelo (sem acento, minúsculo) contra os aliases/enum."""
    if not isinstance(valor, str):
        return None
    chave = _sem_acento(valor).strip().lower().replace(" ", "_").replace("-", "_")
    if chave in validos:
        return chave
    return alias.get(chave)


def classificar_triagem(texto: str, modelo: str | None = None) -> dict | None:
    """Uma chamada de classificação (tipo/gravidade/confianca) com o modelo de
    triagem (ou `modelo` explícito, p/ benchmark). `format=json` + few-shot +
    normalização de rótulos para robustez nos nano. Retorna o JSON validado ou None.
    Isola a etapa de classificação da conversa/guardrails — usada pelo `make bench`."""
    llm = _chat(modelo or TRIAGEM_MODEL, fmt="json")
    if llm is None:
        return None
    try:
        data = _parse_json(llm.invoke(_PROMPT_TRIAGEM_PREFIXO + f'"{texto}"').content)
    except Exception:
        return None
    if not data:
        return None
    tipo = _norm(data.get("tipo"), _TIPO_ALIAS, TipoOcorrencia._value2member_map_)
    if not tipo:
        return None
    out = {"tipo": tipo, "confianca": float(data.get("confianca", 0.6) or 0.6)}
    grav = _norm(data.get("gravidade"), _GRAV_ALIAS, Gravidade._value2member_map_)
    if grav:
        out["gravidade"] = grav
    return out


def _node_triagem(state: _Estado) -> _Estado:
    data = classificar_triagem(state.get("texto", ""))
    if data:
        state["tipo"] = data["tipo"]
        if "gravidade" in data:
            state["gravidade"] = data["gravidade"]
        state["confianca"] = data["confianca"]
    return state


def _node_guardrails(state: _Estado) -> _Estado:
    t = (state.get("texto") or "").lower()
    critico = any(s in t for s in SINAIS_CRITICOS)
    if critico:
        state["escalonar_humano"] = True
        state["gravidade"] = Gravidade.risco_imediato.value
    else:
        state.setdefault("escalonar_humano", False)
    return state


def _node_roteamento(state: _Estado) -> _Estado:
    tipo = TipoOcorrencia(state.get("tipo", "ouvidoria"))
    modo = Modo(state.get("modo", "normal"))
    emergencia = state.get("gravidade") == Gravidade.risco_imediato.value
    r = rotear(tipo, modo, emergencia=emergencia)
    state.setdefault("gravidade", r["gravidade"].value)
    state["canal_sugerido"] = r["canal_roteado"]
    state.setdefault("mensagem_acolhimento", _acolhimento(tipo, modo))
    return state


_compiled = None


def _build_graph():
    global _compiled
    if _compiled is not None:
        return _compiled
    g = StateGraph(_Estado)
    g.add_node("conversa", _node_conversa)
    g.add_node("triagem", _node_triagem)
    g.add_node("guardrails", _node_guardrails)
    g.add_node("roteamento", _node_roteamento)
    g.set_entry_point("conversa")
    g.add_edge("conversa", "triagem")
    g.add_edge("triagem", "guardrails")
    g.add_edge("guardrails", "roteamento")
    g.add_edge("roteamento", END)
    _compiled = g.compile()
    return _compiled


# Ordem de proteção: quanto maior, mais protetivo (não pode ser rebaixado).
_RANK_GRAV = {
    Gravidade.orientacao.value: 1,
    Gravidade.risco_potencial.value: 2,
    Gravidade.risco_imediato.value: 3,
}


def _merge_protetivo(seed: dict, out: _Estado, modo: Modo, fonte: str = "agentes") -> dict:
    """A IA/classificador pode refinar o acolhimento e a classificação, mas NUNCA
    rebaixar a proteção: vale sempre a categoria/gravidade mais protetiva entre a
    heurística e a fonte (`fonte` identifica quem classificou: classificador|agentes)."""
    tipo_llm = out.get("tipo", seed["tipo_sugerido"])
    crise = seed["escalonar_humano"] or _RANK_GRAV.get(seed["gravidade"], 1) == 3
    if crise:
        # Em crise, o roteamento segue a rede determinística (o LLM só acolhe).
        tipo_final = seed["tipo_sugerido"]
    elif tipo_llm == TipoOcorrencia.ouvidoria.value and seed["tipo_sugerido"] != TipoOcorrencia.ouvidoria.value:
        # LLM rebaixou para 'ouvidoria', mas a heurística viu algo mais sério.
        tipo_final = seed["tipo_sugerido"]
    else:
        tipo_final = tipo_llm

    grav_final = max(
        seed["gravidade"], out.get("gravidade", seed["gravidade"]),
        key=lambda g: _RANK_GRAV.get(g, 1),
    )
    escalonar = bool(out.get("escalonar_humano") or seed["escalonar_humano"])

    # Canal coerente com o tipo final.
    emergencia = grav_final == Gravidade.risco_imediato.value
    r = rotear(TipoOcorrencia(tipo_final), modo, emergencia=emergencia)
    confianca_final = round(float(out.get("confianca", seed["confianca"])), 2)
    return {
        "tipo_sugerido": tipo_final,
        "gravidade": grav_final,
        "confianca": confianca_final,
        "mensagem_acolhimento": out.get("mensagem_acolhimento", seed["mensagem_acolhimento"]),
        "canal_sugerido": r["canal_roteado"],
        "escalonar_humano": escalonar,
        "fonte": fonte,
        "nivel": _nivel(grav_final, confianca_final, escalonar),
    }


def triagem_conversacional(texto: str, modo: Modo = Modo.normal) -> dict:
    """Executa a triagem. Sempre retorna um resultado válido, com merge protetivo.

    Ordem de precedência (sem Hailo):
    1. Classificador especializado local (governa; offline, ~ms) — não depende de
       LangGraph/Ollama. O merge protetivo garante que ele não rebaixe a proteção
       (sinais críticos da heurística e gravidade mais protetiva prevalecem).
    2. LLM via LangGraph (refino facilitado, ex.: Ollama remoto) — só quando o
       classificador não está treinado/disponível.
    3. Heurística determinística — rede de segurança final.
    """
    seed = _heuristica(texto, modo)  # base segura (inclui sinais críticos)

    clf = classificador.classificar(texto)
    if clf:
        out: _Estado = {"tipo": clf["tipo"], "confianca": clf["confianca"]}
        if clf.get("gravidade"):
            out["gravidade"] = clf["gravidade"]
        return _merge_protetivo(seed, out, modo, fonte="classificador")

    if not (AGENTS_ENABLED and LANGGRAPH_OK):
        return seed
    try:
        estado: _Estado = {
            "texto": texto, "modo": modo.value,
            "tipo": seed["tipo_sugerido"], "gravidade": seed["gravidade"],
        }
        out = _build_graph().invoke(estado)
        return _merge_protetivo(seed, out, modo)
    except Exception:
        # Qualquer falha (Ollama fora, timeout, parse) cai na heurística.
        return _heuristica(texto, modo)


def conversa_voz(historico: list[dict], modo: Modo = Modo.normal) -> dict:
    """Conversa de triagem por voz (multi-turno).

    Decide a próxima fala do atendimento e se já há informação suficiente para
    concluir (com tipo/gravidade/canal). Em sinal crítico, conclui de imediato —
    em emergência não se fica perguntando.
    """
    usuario = [h.get("texto", "") for h in historico if h.get("papel") == "usuario"]
    texto_total = " ".join(t for t in usuario if t).strip()
    if not texto_total:
        return {"fala": "Pode falar. Estou ouvindo você.", "concluido": False,
                "escalonar_humano": False}

    seed = _heuristica(texto_total, modo)
    critico = seed["escalonar_humano"] or _RANK_GRAV.get(seed["gravidade"], 1) == 3
    n_turnos = len(usuario)

    def concluir(fala: str) -> dict:
        final = triagem_conversacional(texto_total, modo)  # aplica o merge protetivo
        return {
            "fala": fala,
            "concluido": True,
            "tipo_sugerido": final["tipo_sugerido"],
            "gravidade": final["gravidade"],
            "canal_sugerido": final["canal_sugerido"],
            "escalonar_humano": final["escalonar_humano"],
            "nivel": final["nivel"],
        }

    if critico:
        return concluir("Entendi, isto é urgente. Já estou acionando ajuda agora. "
                        "Fique em um local seguro se for possível.")
    # Sem LLM ou após 3 turnos, conclui para não cansar quem pede ajuda.
    if not (AGENTS_ENABLED and LANGGRAPH_OK) or n_turnos >= 3:
        return concluir(seed["mensagem_acolhimento"] + " Já vou encaminhar o seu pedido.")

    # LLM gera a próxima pergunta de acolhimento (ou sinaliza PRONTO).
    historico_txt = "\n".join(
        ("Pessoa: " if h.get("papel") == "usuario" else "Atendente: ") + h.get("texto", "")
        for h in historico
    )
    prompt = (
        "Você é o atendente de acolhimento de um totem de emergência universitário. "
        "Em português, faça UMA pergunta curta, calma e acolhedora para entender melhor "
        "a situação (sem dar instrução clínica ou jurídica). Se já houver informação "
        "suficiente para encaminhar, responda apenas a palavra PRONTO.\n\n"
        f"{historico_txt}\nAtendente:"
    )
    try:
        resposta = _chat(CONVERSA_MODEL).invoke(prompt).content.strip()
        if "PRONTO" in resposta.upper() or len(resposta) < 2:
            return concluir(seed["mensagem_acolhimento"] + " Já vou encaminhar o seu pedido.")
        return {"fala": resposta[:240], "concluido": False, "escalonar_humano": False}
    except Exception:
        return concluir(seed["mensagem_acolhimento"] + " Já vou encaminhar o seu pedido.")


def status_agentes() -> dict:
    return {
        "agents_enabled": AGENTS_ENABLED,
        "langgraph_disponivel": LANGGRAPH_OK,
        "ollama_url": OLLAMA_BASE_URL,
        "modelo": OLLAMA_MODEL,
        "triagem_modelo": TRIAGEM_MODEL,
        "conversa_modelo": CONVERSA_MODEL,
        "classificador": classificador.status(),
        "modo": "classificador" if classificador.disponivel()
                else ("agentes" if (AGENTS_ENABLED and LANGGRAPH_OK) else "heuristica"),
    }


# --- Exposição para plotagem / LangGraph Studio ---------------------------
# `langgraph dev` importa este objeto (ver langgraph.json -> graphs.triagem).
graph = _build_graph() if LANGGRAPH_OK else None


def exportar_mermaid() -> str:
    """Retorna o grafo em Mermaid (para docs/plotagem offline)."""
    if graph is None:
        raise RuntimeError("LangGraph indisponível para exportar o grafo.")
    return graph.get_graph().draw_mermaid()
