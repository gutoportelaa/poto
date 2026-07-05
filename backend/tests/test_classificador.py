"""Classificador especializado de triagem — treina um modelo minúsculo em tmp e
prediz. Pulado se o scikit-learn não estiver instalado (extra `clf`)."""

from __future__ import annotations

import pytest

pytest.importorskip("sklearn")

from app import classificador  # noqa: E402


_TREINO = [
    {"texto": "tem um homem armado no corredor", "tipo": "seguranca", "gravidade": "risco_imediato"},
    {"texto": "vi pessoas estranhas rondando o campus", "tipo": "seguranca", "gravidade": "risco_potencial"},
    {"texto": "qual o ramal da segurança?", "tipo": "seguranca", "gravidade": "orientacao"},
    {"texto": "meu ex está aqui e quer me bater", "tipo": "mulher", "gravidade": "risco_imediato"},
    {"texto": "um colega manda mensagens de assédio", "tipo": "mulher", "gravidade": "risco_potencial"},
    {"texto": "como funciona a sala lilás?", "tipo": "mulher", "gravidade": "orientacao"},
    {"texto": "uma pessoa desmaiou e não acorda", "tipo": "saude", "gravidade": "risco_imediato"},
    {"texto": "torci o tornozelo na quadra", "tipo": "saude", "gravidade": "risco_potencial"},
    {"texto": "onde fica a enfermaria?", "tipo": "saude", "gravidade": "orientacao"},
    {"texto": "quero reclamar da limpeza dos banheiros", "tipo": "ouvidoria", "gravidade": "orientacao"},
    {"texto": "gostaria de elogiar a biblioteca", "tipo": "ouvidoria", "gravidade": "orientacao"},
    {"texto": "quero denunciar corrupção no setor", "tipo": "ouvidoria", "gravidade": "risco_potencial"},
]


@pytest.fixture()
def _modelo(tmp_path, monkeypatch):
    caminho = str(tmp_path / "clf.joblib")
    monkeypatch.setattr(classificador, "CLF_PATH", caminho)
    classificador._modelo = None
    classificador.treinar(_TREINO, caminho)
    yield
    classificador._modelo = None


def test_disponivel(_modelo):
    assert classificador.disponivel()


def test_classifica_saude(_modelo):
    # frase in-distribution p/ o modelo minúsculo de teste (valida o pipeline,
    # não a acurácia — esta é medida em make train-clf / make bench).
    r = classificador.classificar("uma pessoa desmaiou no corredor")
    assert r and r["tipo"] == "saude"
    assert 0.0 <= r["confianca"] <= 1.0
    assert r["gravidade"] in {"risco_imediato", "risco_potencial", "orientacao"}


def test_classifica_seguranca(_modelo):
    r = classificador.classificar("tem um cara armado ameaçando todo mundo")
    assert r and r["tipo"] == "seguranca"


def test_texto_vazio_retorna_none(_modelo):
    assert classificador.classificar("   ") is None


def test_indisponivel_sem_modelo(tmp_path, monkeypatch):
    monkeypatch.setattr(classificador, "CLF_PATH", str(tmp_path / "inexistente.joblib"))
    classificador._modelo = None
    assert not classificador.disponivel()
    assert classificador.classificar("qualquer texto") is None
