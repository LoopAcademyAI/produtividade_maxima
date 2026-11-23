"""R1: notas no servidor. Corre em SQLite e com o modelo simulado: python test_notas.py"""

import os
import tempfile
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

os.environ["NOTAS_SQLITE"] = os.path.join(tempfile.mkdtemp(), "teste.db")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

import app


def modelo(conteudo):
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
    ana, rui = {"X-Utilizador": str(uuid.uuid4())}, {"X-Utilizador": str(uuid.uuid4())}
    with (
        TestClient(app.app) as client,
        patch.dict(os.environ, {"NVIDIA_API_KEY": "chave-de-teste"}),
    ):
        assert client.get("/api/notas").status_code == 400, "sem utilizador → 400"

        with patch.object(app, "OpenAI", return_value=modelo("tarefa")):
            r = client.post(
                "/api/notas",
                json={"texto": "Devolver o carregador ao João"},
                headers=ana,
            )
        assert r.status_code == 201 and r.json()["categoria"] == "tarefa"
        id_ana = r.json()["id"]
        with patch.object(app, "OpenAI", return_value=modelo("ideia")):
            client.post("/api/notas", json={"texto": "App para relógios"}, headers=ana)
            client.post("/api/notas", json={"texto": "Nota do Rui"}, headers=rui)

        assert len(client.get("/api/notas", headers=ana).json()) == 2, (
            "a Ana vê só as dela"
        )
        assert len(client.get("/api/notas", headers=rui).json()) == 1, (
            "o Rui vê só a dele"
        )
        assert [
            n["texto"]
            for n in client.get("/api/notas?categoria=ideia", headers=ana).json()
        ] == ["App para relógios"]
        assert len(client.get("/api/notas?q=CARREGADOR", headers=ana).json()) == 1, (
            "procura ignora maiúsculas"
        )
        assert (
            client.get("/api/notas?categoria=inventada", headers=ana).status_code == 422
        )

        assert client.delete(f"/api/notas/{id_ana}", headers=rui).status_code == 404, (
            "o Rui não apaga notas da Ana"
        )
        assert client.delete(f"/api/notas/{id_ana}", headers=ana).status_code == 204

        antigas = [
            {
                "id": "a1",
                "texto": "nota antiga",
                "categoria": "pessoal",
                "criada": "2026-11-20T10:00:00Z",
            },
            {"id": "a2", "texto": "categoria estranha", "categoria": "compra"},
        ]
        assert client.post("/api/notas/importar", json=antigas, headers=ana).json() == {
            "importadas": 1,
            "ignoradas": 1,
        }
        assert (
            client.post("/api/notas/importar", json=antigas, headers=ana).json()[
                "importadas"
            ]
            == 0
        ), "importar 2× não duplica"

        with patch.object(app, "OpenAI", return_value=modelo("E")):
            assert (
                client.post("/api/notas", json={"texto": "x"}, headers=ana).status_code
                == 502
            ), "categoria inválida não é guardada"
        assert len(client.get("/api/notas", headers=ana).json()) == 2
    print(
        "OK: criar, listar (por pessoa, categoria, procura), apagar, importar e erros."
    )


if __name__ == "__main__":
    main()
