"""Testes locais do contrato e do grafo do agente, sem rede ou chaves reais."""

import io
import logging
import os
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import app
from agente import RESPOSTA_LIMITE

UTILIZADOR_TESTE = "11111111-1111-4111-8111-111111111111"
UTILIZADOR_PRIVADO = "22222222-2222-4222-8222-222222222222"


def testar_cabecalho_obrigatorio(client: TestClient):
    resposta = client.post("/api/agente", json={"mensagem": "Olá"})
    assert resposta.status_code == 400, resposta.text
    assert "X-Utilizador" in resposta.json()["detail"]

    resposta = client.post(
        "/api/agente",
        headers={"X-Utilizador": "   "},
        json={"mensagem": "Olá"},
    )
    assert resposta.status_code == 400, resposta.text

    resposta = client.post(
        "/api/agente",
        headers={"X-Utilizador": "nao-e-uuid"},
        json={"mensagem": "Olá"},
    )
    assert resposta.status_code == 400, resposta.text


def testar_formato_e_conversa(client: TestClient):
    modelo = {"texto": "Posso ajudar com isso.", "chamadas": []}
    with patch.object(app, "chamar_modelo_agente", return_value=modelo):
        resposta = client.post(
            "/api/agente",
            headers={"X-Utilizador": UTILIZADOR_TESTE},
            json={"mensagem": "Olá", "conversa": "conversa-existente"},
        )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json() == {
        "resposta": "Posso ajudar com isso.",
        "conversa": "conversa-existente",
        "ferramentas": [],
        "pendente": None,
    }

    with patch.object(app, "chamar_modelo_agente", return_value=modelo):
        resposta = client.post(
            "/api/agente",
            headers={"X-Utilizador": UTILIZADOR_TESTE},
            json={"mensagem": "Olá"},
        )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["conversa"]


def testar_adaptador_de_chamadas_de_ferramenta():
    resposta_falsa = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="chamada-1",
                            type="function",
                            function=SimpleNamespace(
                                name="ferramenta_em_desenvolvimento",
                                arguments='{"operacao":"listar","argumentos":{}}',
                            ),
                        )
                    ],
                ),
            )
        ],
    )
    cliente = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_kwargs: resposta_falsa),
        ),
    )
    with (
        patch.dict(os.environ, {"NVIDIA_API_KEY": "chave-de-teste"}),
        patch.object(app, "OpenAI", return_value=cliente),
    ):
        resultado = app.chamar_modelo_agente([], "request-id-teste")

    assert resultado == {
        "texto": "",
        "chamadas": [
            {
                "id": "chamada-1",
                "nome": "ferramenta_em_desenvolvimento",
                "args": {"operacao": "listar", "argumentos": {}},
            }
        ],
    }


def testar_chamada_de_ferramenta_custom_rejeitada():
    resposta_falsa = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[SimpleNamespace(id="chamada-1", type="custom")],
                ),
            )
        ],
    )
    cliente = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_kwargs: resposta_falsa),
        ),
    )
    with (
        patch.dict(os.environ, {"NVIDIA_API_KEY": "chave-de-teste"}),
        patch.object(app, "OpenAI", return_value=cliente),
    ):
        try:
            app.chamar_modelo_agente([], "request-id-teste")
        except app.HTTPException as exc:
            assert exc.status_code == 502
        else:
            raise AssertionError("Uma chamada custom deve ser rejeitada.")


def testar_limite_de_passos_e_privacidade(client: TestClient, log: io.StringIO):
    chamadas_modelo = []

    def pedir_ferramenta(mensagens, request_id):
        chamadas_modelo.append((mensagens, request_id))
        return {
            "texto": "",
            "chamadas": [
                {
                    "id": f"chamada-{len(chamadas_modelo)}",
                    "nome": "ferramenta_em_desenvolvimento",
                    "args": {
                        "operacao": "teste",
                        "argumentos": {"marcador": "argumento-privado"},
                    },
                }
            ],
        }

    with patch.object(app, "chamar_modelo_agente", side_effect=pedir_ferramenta):
        resposta = client.post(
            "/api/agente",
            headers={"X-Utilizador": UTILIZADOR_PRIVADO},
            json={"mensagem": "mensagem-privada", "conversa": "conversa-limite"},
        )

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert len(chamadas_modelo) == 6
    assert len(corpo["ferramentas"]) == 6
    assert corpo["resposta"] == RESPOSTA_LIMITE
    assert corpo["conversa"] == "conversa-limite" and corpo["pendente"] is None
    assert any(mensagem["role"] == "tool" for mensagem in chamadas_modelo[1][0])
    assert "mensagem-privada" not in log.getvalue()
    assert UTILIZADOR_PRIVADO not in log.getvalue()
    assert "argumento-privado" not in log.getvalue()


def testar_chave_em_falta(client: TestClient):
    with patch.dict(os.environ, {"NVIDIA_API_KEY": ""}):
        resposta = client.post(
            "/api/agente",
            headers={"X-Utilizador": UTILIZADOR_TESTE},
            json={"mensagem": "Olá"},
        )
    assert resposta.status_code == 503, resposta.text


def main():
    log = io.StringIO()
    handlers = app.logger.handlers[:]
    app.logger.handlers = [logging.StreamHandler(log)]
    try:
        with TestClient(app.app, raise_server_exceptions=False) as client:
            testar_cabecalho_obrigatorio(client)
            testar_formato_e_conversa(client)
            testar_adaptador_de_chamadas_de_ferramenta()
            testar_chamada_de_ferramenta_custom_rejeitada()
            testar_limite_de_passos_e_privacidade(client, log)
            testar_chave_em_falta(client)
        print(
            "OK: X-Utilizador em falta/vazio -> 400; formato de resposta e conversa validos."
        )
        print(
            "OK: ciclo do modelo -> termina apos 6 chamadas; logs sem conteudo privado."
        )
        print("OK: NVIDIA_API_KEY em falta -> 503.")
    finally:
        app.logger.handlers = handlers


if __name__ == "__main__":
    main()
