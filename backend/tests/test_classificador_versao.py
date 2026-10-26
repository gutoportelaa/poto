"""#13: o artefato registra a versão do sklearn e avisa quando ela muda."""
import logging

import pytest

pytest.importorskip("sklearn")

from app import classificador  # noqa: E402


def test_artefato_grava_versao(tmp_path):
    import joblib
    import sklearn
    caminho = str(tmp_path / "clf.joblib")
    dados = [{"texto": "fogo no bloco", "tipo": "seguranca", "gravidade": "risco_imediato"},
             {"texto": "como marcar consulta", "tipo": "saude", "gravidade": "orientacao"}]
    classificador.treinar(dados, caminho)
    assert joblib.load(caminho)["sklearn"] == sklearn.__version__


def test_avisa_quando_versao_difere(caplog):
    with caplog.at_level(logging.WARNING):
        classificador._avisar_versao({"sklearn": "0.0.0"})
    assert "retreine" in caplog.text


def test_silencioso_na_mesma_versao(caplog):
    import sklearn
    with caplog.at_level(logging.WARNING):
        classificador._avisar_versao({"sklearn": sklearn.__version__})
    assert caplog.text == ""
