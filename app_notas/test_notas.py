"""Compatibilidade offline do endpoint principal do classificador."""
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import app


def resposta_fake(conteudo):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=conteudo))]
        )
    )))


def main():
    with patch.dict(app.os.environ, {"NVIDIA_API_KEY": "chave-simulada"}), \
            patch.object(app, "OpenAI", return_value=resposta_fake("tarefa")), \
            TestClient(app.app, raise_server_exceptions=False) as client:
        resposta = client.post("/api/classificar", json={"texto": "Comprar pão"})
        assert resposta.status_code == 200
        assert resposta.json() == {"categoria": "tarefa"}

        vazia = client.post("/api/classificar", json={"texto": "   "})
        assert vazia.status_code == 422

    print("OK: classificação válida, resposta JSON e nota vazia.")


if __name__ == "__main__":
    main()
