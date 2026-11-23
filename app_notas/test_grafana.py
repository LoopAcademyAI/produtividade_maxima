import base64
import io
import json
import logging
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient
import app


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return b""


def main():
    env = {
        "LOKI_PUSH_URL": "https://logs-test.grafana.net/loki/api/v1/push",
        "LOKI_USER": "123",
        "LOKI_TOKEN": "token-teste",
    }
    requests = []

    def fake(request, timeout):
        requests.append(request)
        assert timeout == 1.5
        return Response()

    with (
        patch.dict(app.os.environ, env),
        patch.object(app, "build_opener", return_value=SimpleNamespace(open=fake)),
    ):
        # Erro inesperado simulado (antes de qualquer chamada à NVIDIA).
        with (
            TestClient(app.app, raise_server_exceptions=False) as client,
            patch.object(app, "criar_prompt", side_effect=ValueError("erro provocado")),
        ):
            response = client.post(
                "/api/classificar", json={"texto": "nota privada de teste"}
            )
            assert response.status_code == 500
    assert len(requests) == 1
    payload = json.loads(requests[0].data)
    event = json.loads(payload["streams"][0]["values"][0][1])
    assert event["event"] == "pedido_erro_inesperado" and event["nivel"] == "error"
    assert "nota privada de teste" not in json.dumps(payload)
    assert (
        requests[0].headers["Authorization"]
        == "Basic " + base64.b64encode(b"123:token-teste").decode()
    )
    with (
        patch.dict(app.os.environ, env),
        patch.object(
            app,
            "build_opener",
            return_value=SimpleNamespace(
                open=lambda *a, **k: (_ for _ in ()).throw(OSError("erro"))
            ),
        ),
        TestClient(app.app, raise_server_exceptions=False) as client,
    ):
        assert client.get("/api/health").status_code == 200
    with (
        patch.dict(
            app.os.environ,
            {**env, "LOKI_PUSH_URL": "https://attacker.example/loki/api/v1/push"},
        ),
        patch.object(app, "build_opener") as mock,
    ):
        app.enviar_loki({"event": "teste"}, logging.INFO)
        mock.assert_not_called()
    print(
        "OK: evento 500 enviado ao Loki simulado; falha de envio não afeta a API; domínio inválido bloqueado."
    )


if __name__ == "__main__":
    main()
