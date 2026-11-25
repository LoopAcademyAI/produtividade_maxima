"""Testes locais do contrato e do grafo do agente, sem rede ou chaves reais."""

import io
import logging
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

os.environ["NOTAS_SQLITE"] = os.path.join(tempfile.mkdtemp(), "teste.db")
os.environ["DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""
os.environ["NVIDIA_API_KEY"] = ""

import app
from agente import RESPOSTA_LIMITE, limitar_historico
from memoria import abrir_checkpointer

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
        if len(chamadas_modelo) > 6:
            return {"texto": "Agora consigo responder.", "chamadas": []}
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

    with patch.object(app, "chamar_modelo_agente", side_effect=pedir_ferramenta):
        resposta_seguinte = client.post(
            "/api/agente",
            headers={"X-Utilizador": UTILIZADOR_PRIVADO},
            json={"mensagem": "Continua.", "conversa": "conversa-limite"},
        )
    assert resposta_seguinte.status_code == 200, resposta_seguinte.text
    mensagens_seguinte = chamadas_modelo[-1][0]
    for indice, mensagem in enumerate(mensagens_seguinte):
        if mensagem.get("role") != "assistant" or not mensagem.get("tool_calls"):
            continue
        respostas_tool = mensagens_seguinte[
            indice + 1 : indice + 1 + len(mensagem["tool_calls"])
        ]
        assert [resposta.get("tool_call_id") for resposta in respostas_tool] == [
            chamada["id"] for chamada in mensagem["tool_calls"]
        ]


def testar_chave_em_falta(client: TestClient):
    with patch.dict(os.environ, {"NVIDIA_API_KEY": ""}):
        resposta = client.post(
            "/api/agente",
            headers={"X-Utilizador": UTILIZADOR_TESTE},
            json={"mensagem": "Olá"},
        )
    assert resposta.status_code == 503, resposta.text


def testar_memoria_persistida_e_isolada():
    utilizador = "33333333-3333-4333-8333-333333333333"
    outro_utilizador = "44444444-4444-4444-8444-444444444444"
    conversa = "memoria-persistida"
    mensagens_enviadas = []

    def modelo(mensagens, _request_id):
        mensagens_enviadas.append(mensagens)
        mensagens_utilizador = [
            str(mensagem.get("content"))
            for mensagem in mensagens
            if mensagem.get("role") == "user"
        ]
        ultima = mensagens_utilizador[-1]
        sabe_nome = any("Chamo-me Inês." in texto for texto in mensagens_utilizador)
        if ultima == "Como me chamo?":
            resposta = "Inês" if sabe_nome else "Não sei."
        else:
            resposta = "Registado."
        return {"texto": resposta, "chamadas": []}

    with patch.object(app, "chamar_modelo_agente", side_effect=modelo):
        with TestClient(app.app) as client:
            resposta = client.post(
                "/api/agente",
                headers={"X-Utilizador": utilizador},
                json={"mensagem": "Chamo-me Inês.", "conversa": conversa},
            )
            assert resposta.status_code == 200, resposta.text

    with patch.object(app, "chamar_modelo_agente", side_effect=modelo):
        with TestClient(app.app) as client:
            mesma_conversa = client.post(
                "/api/agente",
                headers={"X-Utilizador": utilizador},
                json={"mensagem": "Como me chamo?", "conversa": conversa},
            )
            outra_conversa = client.post(
                "/api/agente",
                headers={"X-Utilizador": utilizador},
                json={"mensagem": "Como me chamo?", "conversa": "outra-conversa"},
            )
            outro_dono = client.post(
                "/api/agente",
                headers={"X-Utilizador": outro_utilizador},
                json={"mensagem": "Como me chamo?", "conversa": conversa},
            )

    assert mesma_conversa.json()["resposta"] == "Inês"
    assert outra_conversa.json()["resposta"] == "Não sei."
    assert outro_dono.json()["resposta"] == "Não sei."
    assert "Chamo-me Inês." in [
        mensagem.get("content") for mensagem in mensagens_enviadas[1]
    ]
    assert "Chamo-me Inês." not in [
        mensagem.get("content") for mensagem in mensagens_enviadas[2]
    ]
    assert "Chamo-me Inês." not in [
        mensagem.get("content") for mensagem in mensagens_enviadas[3]
    ]


def testar_limite_de_historico_enviado_ao_modelo():
    utilizador = "55555555-5555-4555-8555-555555555555"
    mensagens_enviadas = []

    def modelo(mensagens, _request_id):
        mensagens_enviadas.append(mensagens)
        return {"texto": "Continuo.", "chamadas": []}

    with patch.object(app, "chamar_modelo_agente", side_effect=modelo):
        with TestClient(app.app) as client:
            for passo in range(12):
                resposta = client.post(
                    "/api/agente",
                    headers={"X-Utilizador": utilizador},
                    json={
                        "mensagem": f"mensagem-{passo}",
                        "conversa": "historico-longo",
                    },
                )
                assert resposta.status_code == 200, resposta.text

    mensagens_finais = mensagens_enviadas[-1]
    historico = [
        mensagem for mensagem in mensagens_finais if mensagem.get("role") != "system"
    ]
    assert any(mensagem.get("role") == "system" for mensagem in mensagens_finais)
    assert len(historico) <= 20
    assert "mensagem-0" not in [
        mensagem.get("content") for mensagem in mensagens_finais
    ]
    assert mensagens_finais[-1].get("content") == "mensagem-11"


def testar_limite_de_historico_nao_deixa_respostas_tool_orfas():
    chamada = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "chamada-1",
                "type": "function",
                "function": {"name": "ferramenta", "arguments": "{}"},
            },
            {
                "id": "chamada-2",
                "type": "function",
                "function": {"name": "ferramenta", "arguments": "{}"},
            },
        ],
    }
    mensagens = [
        {"role": "system", "content": "Instruções."},
        *[{"role": "user", "content": f"antiga-{indice}"} for indice in range(5)],
        chamada,
        {"role": "tool", "tool_call_id": "chamada-1", "content": "resultado-1"},
        {"role": "tool", "tool_call_id": "chamada-2", "content": "resultado-2"},
        *[{"role": "user", "content": f"recente-{indice}"} for indice in range(18)],
    ]

    historico = limitar_historico(mensagens)

    assert historico[0] == mensagens[0]
    assert len(historico) <= 21
    assert historico[1].get("role") != "tool"
    assert all(
        mensagem.get("role") != "assistant" or not mensagem.get("tool_calls")
        for mensagem in historico[1:]
    )


def testar_vercel_sem_postgres_falha_sem_fallback():
    with patch.dict(
        os.environ,
        {"VERCEL": "1", "DATABASE_URL": "", "POSTGRES_URL": ""},
    ):
        try:
            with abrir_checkpointer():
                raise AssertionError("A Vercel não deve usar SQLite como fallback.")
        except RuntimeError as exc:
            assert "DATABASE_URL" in str(exc)


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
        testar_memoria_persistida_e_isolada()
        testar_limite_de_historico_enviado_ao_modelo()
        testar_limite_de_historico_nao_deixa_respostas_tool_orfas()
        testar_vercel_sem_postgres_falha_sem_fallback()
        print(
            "OK: cabeçalho, formato de resposta, conversa persistida e isolamento validos."
        )
        print(
            "OK: limite de 6 chamadas, historico de 20 mensagens e logs sem conteudo privado."
        )
        print("OK: NVIDIA_API_KEY em falta -> 503.")
    finally:
        app.logger.handlers = handlers


if __name__ == "__main__":
    main()
