"""R4.1: JSON Schema no pedido e respostas inválidas tratadas sem rede."""

import io
import json
import logging
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import app


def cliente_falso(conteudo: str, pedidos: list[dict]) -> SimpleNamespace:
    def criar(**kwargs):
        pedidos.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=conteudo))]
        )

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=criar))
    )


def main() -> None:
    log = io.StringIO()
    handlers_antigos = app.logger.handlers[:]
    app.logger.handlers = [logging.StreamHandler(log)]
    try:
        pedidos: list[dict] = []
        with (
            TestClient(app.app, raise_server_exceptions=False) as client,
            patch.dict(app.os.environ, {"NVIDIA_API_KEY": "chave-simulada"}),
            patch.object(
                app,
                "OpenAI",
                return_value=cliente_falso('{"categoria":"tarefa"}', pedidos),
            ),
        ):
            resposta = client.post("/api/classificar", json={"texto": "Comprar pão"})
        assert resposta.status_code == 200
        assert resposta.json() == {"categoria": "tarefa"}
        assert pedidos[0]["response_format"] == app.FORMATO_CATEGORIA
        schema = pedidos[0]["response_format"]["json_schema"]["schema"]
        assert schema["properties"]["categoria"]["enum"] == app.CATEGORIES
        assert schema["additionalProperties"] is False

        log.seek(0)
        log.truncate(0)
        with (
            TestClient(app.app, raise_server_exceptions=False) as client,
            patch.dict(app.os.environ, {"NVIDIA_API_KEY": "chave-simulada"}),
            patch.object(
                app,
                "OpenAI",
                return_value=cliente_falso('{"categoria":"inventada"}', []),
            ),
        ):
            resposta = client.post("/api/classificar", json={"texto": "nota privada"})
        assert resposta.status_code == 502
        eventos = [json.loads(linha) for linha in log.getvalue().splitlines()]
        assert any(evento["event"] == "categoria_invalida" for evento in eventos)
        assert "nota privada" not in log.getvalue()
    finally:
        app.logger.handlers = handlers_antigos

    print("OK: JSON Schema, categoria válida e resposta fora do schema → 502 seguro.")


if __name__ == "__main__":
    main()
