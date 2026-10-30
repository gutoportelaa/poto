"""Regressão dos sinais críticos (issue #12): casos graves que a heurística perdia
e falsos positivos que a correção NÃO pode introduzir."""

from __future__ import annotations

import pytest

from app.agents.graph import _eh_critico, _heuristica
from app.models import Modo

GRAVES = [
    "vi fumaça saindo do laboratório de química",
    "meu ex está aqui e disse que vai me machucar",
    "um homem está me agarrando à força",
    "alguém arrombou a porta e entrou na sala",
    "tem um cara armado no estacionamento do CCS",
    "um homem está ameaçando as pessoas com uma faca no RU",
    "ouvi tiros perto da portaria principal",
    "meu namorado está me batendo no estacionamento",
    "uma amiga está sendo espancada pelo namorado no pátio",
    "um professor teve um infarto na sala",
    "um senhor engasgou no RU e não consegue falar",
    "um aluno diabético está desacordado e inconsciente",
    "tem fogo no corredor do bloco de engenharia",
    "MEU EX VAI ME MACHUCAR!!!",
]

NAO_CRITICOS = [
    "arrombaram o armário do vestiário e levaram as coisas dos alunos",
    "qual o procedimento em caso de incêndio no prédio",
    "onde ficam os extintores do bloco de humanidades",
    "como faço uma reclamação sobre a limpeza dos banheiros",
    "quero informações sobre a sala lilás",
    "onde fica o posto médico do campus",
]


@pytest.mark.parametrize("texto", GRAVES)
def test_sinal_critico_detectado(texto):
    assert _eh_critico(texto), texto
    r = _heuristica(texto, Modo.normal)
    assert r["gravidade"] == "risco_imediato" and r["escalonar_humano"]


@pytest.mark.parametrize("texto", NAO_CRITICOS)
def test_sem_falso_positivo(texto):
    assert not _eh_critico(texto), texto


def test_crise_sem_categoria_nao_vai_para_ouvidoria():
    """Risco imediato sem palavra-chave de categoria: o tipo vem da fonte (e
    'ouvidoria' é promovida a 'seguranca'), nunca roteia crise para a Ouvidoria."""
    from app.agents.graph import _merge_protetivo
    texto = "vi fumaça saindo do laboratório de química"
    seed = _heuristica(texto, Modo.normal)
    assert seed["tipo_sugerido"] == "ouvidoria" and seed["confianca"] <= 0.3
    r = _merge_protetivo(seed, {"tipo": "ouvidoria", "confianca": 0.7}, Modo.normal)
    assert r["tipo_sugerido"] == "seguranca" and r["gravidade"] == "risco_imediato"
    r = _merge_protetivo(seed, {"tipo": "saude", "confianca": 0.7}, Modo.normal)
    assert r["tipo_sugerido"] == "saude"
