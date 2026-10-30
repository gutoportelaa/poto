"""#21/#24: o assistente responde só do que tem fonte e avisa sobre denúncia anônima."""
from app import ouvidoria


def test_todo_fato_tem_fonte_e_status_valido():
    for chave, f in ouvidoria.fatos().items():
        assert f["fonte"], chave
        assert f["status"] in ("norma", "portal", "a_confirmar"), chave
        if f["status"] == "a_confirmar":
            assert f["texto"] is None, f"{chave}: dado não confirmado não pode ter texto"


def test_prazo_vem_da_base_com_fonte():
    r = ouvidoria.orientar("Qual o prazo de resposta da ouvidoria?")
    assert "30 dias" in r["resposta"]
    assert any("13.460" in f for f in r["fontes"])


def test_anonimo_avisa_sem_protocolo_nem_resposta():
    r = ouvidoria.orientar("quero fazer uma denúncia anônima, ninguém pode saber que fui eu")
    assert r["aviso_anonimato"] and "não gera protocolo" in r["aviso_anonimato"]
    assert "protocolo" in r["resposta"]


def test_aviso_nao_aparece_sem_anonimato():
    assert ouvidoria.orientar("quero elogiar a biblioteca")["aviso_anonimato"] is None


def test_email_nao_confirmado_nunca_e_respondido():
    r = ouvidoria.orientar("qual o e-mail e o telefone da ouvidoria?")
    assert "@" not in (r["resposta"] or "")
    assert "3237-2104" in r["resposta"]


def test_sem_cobertura_nao_inventa():
    r = ouvidoria.orientar("quanto custa o restaurante universitário?")
    assert r["resposta"] is None and r["fontes"] == []


def test_nunca_promete_retorno_a_quem_nao_se_identifica():
    r = ouvidoria.orientar("denúncia anônima, vou receber resposta?")
    assert "receberá" not in (r["resposta"] or "").lower()
    assert "não permite resposta" in r["resposta"]


def test_endpoint_triagem_traz_aviso_de_anonimato():
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        r = c.post("/api/v1/triagem", json={
            "texto": "quero denunciar um professor que vende notas, de forma anônima", "modo": "normal"})
    assert r.status_code == 200
    assert "não gera protocolo" in r.json()["aviso_anonimato"]


def test_endpoint_nao_polui_triagem_comum():
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        r = c.post("/api/v1/triagem", json={"texto": "desmaiou no corredor", "modo": "normal"})
    assert r.json()["aviso_anonimato"] is None and r.json()["orientacao_ouvidoria"] is None
