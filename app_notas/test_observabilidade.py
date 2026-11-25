"""Experiência local: resposta inválida, falha inesperada e logs sem dados da nota."""

import io
import json
import logging
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import app


def resposta_fake(conteudo):
    conteudo = json.dumps({"categoria": conteudo})
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=conteudo))]
                )
            )
        )
    )


def main():
    log = io.StringIO()
    old_handlers = app.logger.handlers[:]
    app.logger.handlers = [logging.StreamHandler(log)]
    try:
        with (
            TestClient(app.app, raise_server_exceptions=False) as client,
            patch.dict(app.os.environ, {"NVIDIA_API_KEY": "chave-de-teste"}),
        ):
            with patch.object(app, "OpenAI", return_value=resposta_fake("E")):
                resposta = client.post(
                    "/api/classificar", json={"texto": "nota privada de teste"}
                )
                assert resposta.status_code == 502
                rid = resposta.headers["x-request-id"]
            events = [json.loads(line) for line in log.getvalue().splitlines()]
            assert any(
                e["event"] == "categoria_invalida" and e["request_id"] == rid
                for e in events
            )
            assert (
                "nota privada de teste" not in log.getvalue()
                and "chave-de-teste" not in log.getvalue()
            )
            with patch.object(app, "OpenAI", return_value=resposta_fake("tarefa")):
                resposta = client.post(
                    "/api/classificar", json={"texto": "Comprar pão"}
                )
                assert (
                    resposta.status_code == 200
                    and resposta.json()["categoria"] == "tarefa"
                )
            with patch.object(
                app, "criar_prompt", side_effect=ValueError("erro provocado")
            ):
                resposta = client.post("/api/classificar", json={"texto": "teste"})
                assert resposta.status_code == 500
            events = [json.loads(line) for line in log.getvalue().splitlines()]
            assert any(
                e["event"] == "pedido_erro_inesperado"
                and e["tipo_erro"] == "ValueError"
                for e in events
            )
            print(
                "OK: resposta E → 502 com categoria_invalida; erro inesperado → 500 com pedido_erro_inesperado; sucesso → 200."
            )
            print(
                "Exemplo de log de erro:",
                next(
                    json.dumps(e, ensure_ascii=False)
                    for e in events
                    if e["event"] == "categoria_invalida"
                ),
            )
    finally:
        app.logger.handlers = old_handlers


if __name__ == "__main__":
    main()
