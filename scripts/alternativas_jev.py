"""Jev (TypeSafe "System One") como alternativa de referência no harness (issue #10).

Não é governante: é API hospedada, exige rede e o texto sairia do campus. Serve só para
medir, com frases SINTÉTICAS (os datasets de `dataset_v2` são todos escritos/gerados),
o quanto um modelo System One treinado para isso ganharia sobre as opções locais.

Só é registrado se `TYPESAFE_API_KEY` estiver definida e `langchain-typesafe` instalada;
sem isso o harness segue normalmente (portabilidade: nada aqui é dependência do projeto).

  jev          duas perguntas `Choice` (tipo, gravidade) numa única requisição
  jev+merge    o mesmo, passado pelo merge protetivo de produção (criado pelo harness)

Dependência:  uv run --with langchain-typesafe ...   (v0.0.1a3 verificada)
"""

from __future__ import annotations

import os

# Mesmas definições dos prompts do verificador/LLM local, para a comparação ser justa.
TIPOS = {
    "seguranca": "ameaça, crime, invasão, briga, incêndio ou perigo físico no campus, ou dúvida sobre a segurança",
    "mulher": "violência, assédio ou importunação contra mulher, ou orientação sobre a rede de proteção",
    "saude": "mal-estar, acidente, emergência clínica, saúde mental ou dúvida sobre atendimento de saúde",
    "ouvidoria": "reclamação, denúncia de irregularidade, sugestão, elogio ou dúvida sobre a ouvidoria",
}
GRAVS = {
    "risco_imediato": "acontecendo AGORA, risco iminente à vida ou integridade",
    "risco_potencial": "situação preocupante ou ameaça difusa, sem perigo iminente",
    "orientacao": "pedido de informação ou orientação, sem risco",
}


def disponivel() -> bool:
    if not os.getenv("TYPESAFE_API_KEY"):
        return False
    try:
        import langchain_typesafe  # noqa: F401
    except ImportError:
        return False
    return True


def registro(Alternativa, client=None) -> dict:  # noqa: N803 — recebe a base do harness
    """`client`: `httpx2.Client` injetável (testes com transporte simulado)."""
    from langchain_typesafe import Choice, TypeSafeClassifier

    class Jev(Alternativa):
        nome = "jev"
        modelo = os.getenv("TYPESAFE_MODEL", "jev-latest")  # fixe uma versão p/ reprodutibilidade

        def fit(self, dados):  # sem treino: o modelo já vem pronto
            kw = {"client": client} if client is not None else {}
            self.clf = TypeSafeClassifier(model=self.modelo, **kw)
            self.tokens = 0
            return self

        def _um(self, texto: str) -> tuple[str, str]:
            r = self.clf.invoke({
                "state": texto,
                "questions": {
                    "tipo": Choice(instructions="Qual o tipo desta mensagem enviada a um totem "
                                                "de emergência da UFPI?", criteria=TIPOS),
                    "gravidade": Choice(instructions="Qual a gravidade da situação descrita?",
                                        criteria=GRAVS),
                },
            })
            self.tokens += (r.usage.input_tokens or 0) + (r.usage.output_tokens or 0)
            return r.choices["tipo"].choice, r.choices["gravidade"].choice

        def predict(self, textos):
            return [self._um(t) for t in textos]

    return {Jev.nome: Jev}
