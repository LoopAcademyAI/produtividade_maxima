"""Testes da lógica à volta do modelo, sem chamar a API (o classificador é simulado)."""

import pytest
from fastapi.testclient import TestClient

import app as servico
from captura.acesso import Limitador, carregar_chaves
from captura.classificador import Resultado, interpretar


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("CAPTURA_KEYS", "ana:chave-ana,rui:chave-rui")
    monkeypatch.setattr(servico, "limitador", Limitador(por_minuto=3, por_dia=5))
    servico.app.dependency_overrides[servico.get_classificar] = lambda: (
        lambda texto: Resultado(categorias={"tarefa"}, modelo="falso", tokens_prompt=10, tokens_resposta=2))
    yield TestClient(servico.app)
    servico.app.dependency_overrides.clear()


def pedir(cliente, chave="chave-ana", texto="comprar pilhas"):
    return cliente.post("/classificar", json={"texto": texto}, headers={"Authorization": f"Bearer {chave}"})


def test_classifica_com_chave_valida(cliente):
    r = pedir(cliente)
    assert r.status_code == 200
    assert r.json()["categorias"] == ["tarefa"]
    assert r.json()["tokens_prompt"] == 10


def test_sem_chave_ou_chave_errada_da_401(cliente):
    assert cliente.post("/classificar", json={"texto": "x"}).status_code == 401
    assert pedir(cliente, chave="inventada").status_code == 401


def test_limite_por_minuto_e_por_utilizador(cliente):
    assert [pedir(cliente).status_code for _ in range(4)] == [200, 200, 200, 429]
    assert pedir(cliente, chave="chave-rui").status_code == 200  # o limite da Ana não é o do Rui


def test_texto_vazio_ou_enorme_e_recusado(cliente):
    assert pedir(cliente, texto="").status_code == 422
    assert pedir(cliente, texto="a" * 2001).status_code == 422


def test_falha_do_modelo_da_502_e_nao_inventa(cliente):
    def rebenta(texto):
        raise TimeoutError

    servico.app.dependency_overrides[servico.get_classificar] = lambda: rebenta
    assert pedir(cliente).status_code == 502


def test_interpretar_so_aceita_categorias_nossas():
    assert interpretar("Tarefa, agenda") == {"tarefa", "agenda"}
    assert interpretar("**trabalho**\nurgente") == {"trabalho"}
    assert interpretar("Não sei") == set()


def test_chaves_ignoram_lixo():
    assert carregar_chaves("ana:x, rui:y,mal,:z") == {"x": "ana", "y": "rui"}


def test_pagina_e_categorias_sao_publicas(cliente):
    assert cliente.get("/").status_code == 200
    assert "tarefa" in cliente.get("/categorias").json()["categorias"]
