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
from typing import TypedDict

from ..config import AGENTS_ENABLED, OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT
from ..models import Gravidade, Modo, TipoOcorrencia
from ..router_engine import rotear

# --- Detecção de disponibilidade do stack de IA --------------------------
LANGGRAPH_OK = False
_llm = None
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
    }


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


def _chat() -> "ChatOllama | None":
    global _llm
    if not LANGGRAPH_OK:
        return None
    if _llm is None:
        _llm = ChatOllama(
            model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL,
            temperature=0, num_predict=200, timeout=OLLAMA_TIMEOUT,
        )
    return _llm


def _parse_json(raw: str) -> dict | None:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _node_conversa(state: _Estado) -> _Estado:
    modo = Modo(state.get("modo", "normal"))
    llm = _chat()
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


def _node_triagem(state: _Estado) -> _Estado:
    llm = _chat()
    if llm is None:
        return state
    prompt = (
        "Classifique a mensagem de um totem de emergência. Responda APENAS JSON: "
        '{"tipo": "seguranca|mulher|saude|ouvidoria", '
        '"gravidade": "risco_imediato|risco_potencial|orientacao", '
        '"confianca": 0.0}. '
        f'Mensagem: "{state.get("texto", "")}"'
    )
    try:
        data = _parse_json(llm.invoke(prompt).content)
        if data and data.get("tipo") in TipoOcorrencia._value2member_map_:
            state["tipo"] = data["tipo"]
            if data.get("gravidade") in Gravidade._value2member_map_:
                state["gravidade"] = data["gravidade"]
            state["confianca"] = float(data.get("confianca", 0.6))
    except Exception:
        pass
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


def _merge_protetivo(seed: dict, out: _Estado, modo: Modo) -> dict:
    """A IA pode refinar o acolhimento e a classificação, mas NUNCA rebaixar a
    proteção: vale sempre a categoria/gravidade mais protetiva entre heurística e LLM."""
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
    return {
        "tipo_sugerido": tipo_final,
        "gravidade": grav_final,
        "confianca": round(float(out.get("confianca", seed["confianca"])), 2),
        "mensagem_acolhimento": out.get("mensagem_acolhimento", seed["mensagem_acolhimento"]),
        "canal_sugerido": r["canal_roteado"],
        "escalonar_humano": escalonar,
        "fonte": "agentes",
    }


def triagem_conversacional(texto: str, modo: Modo = Modo.normal) -> dict:
    """Executa o pipeline de agentes. Sempre retorna um resultado válido."""
    if not (AGENTS_ENABLED and LANGGRAPH_OK):
        return _heuristica(texto, modo)
    try:
        seed = _heuristica(texto, modo)  # base segura
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
        resposta = _chat().invoke(prompt).content.strip()
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
        "modo": "agentes" if (AGENTS_ENABLED and LANGGRAPH_OK) else "heuristica",
    }


# --- Exposição para plotagem / LangGraph Studio ---------------------------
# `langgraph dev` importa este objeto (ver langgraph.json -> graphs.triagem).
graph = _build_graph() if LANGGRAPH_OK else None


def exportar_mermaid() -> str:
    """Retorna o grafo em Mermaid (para docs/plotagem offline)."""
    if graph is None:
        raise RuntimeError("LangGraph indisponível para exportar o grafo.")
    return graph.get_graph().draw_mermaid()
