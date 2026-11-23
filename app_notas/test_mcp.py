"""Experiência local: tool MCP classificar_nota via /mcp, com o modelo NVIDIA simulado e chaves por tester."""

import io
import json
import logging
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient
import app

CHAVE_ANA = "chave-de-teste-da-ana-0123456789"
TESTERS = json.dumps(
    {"ana": CHAVE_ANA, "rui": "chave-de-teste-do-rui-0123456789", "curta": "abc"}
)
CABECALHOS = {
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-06-18",
    "Authorization": f"Bearer {CHAVE_ANA}",
}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "teste", "version": "0"},
    },
}


def resposta_fake(conteudo):
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=conteudo))]
                )
            )
        )
    )


def rpc(client, method, params=None, id_=1):
    resposta = client.post(
        "/mcp",
        headers=CABECALHOS,
        json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}},
    )
    assert resposta.status_code == 200, (resposta.status_code, resposta.text)
    return resposta.json()


def chamar(client, texto):
    return rpc(
        client,
        "tools/call",
        {"name": "classificar_nota", "arguments": {"texto": texto}},
    )["result"]


def testar_chaves(client, log):
    sem_auth = {k: v for k, v in CABECALHOS.items() if k != "Authorization"}
    casos = {
        "sem chave": sem_auth,
        "chave errada": {
            **sem_auth,
            "Authorization": "Bearer chave-que-nao-existe-0123456789",
        },
        "esquema errado": {**sem_auth, "Authorization": f"Basic {CHAVE_ANA}"},
        "chave curta configurada": {**sem_auth, "Authorization": "Bearer abc"},
    }
    for nome, cabecalhos in casos.items():
        r = client.post("/mcp", headers=cabecalhos, json=INITIALIZE)
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer", (
            nome,
            r.status_code,
        )
    assert (
        client.post(
            "/mcp",
            headers={
                **sem_auth,
                "Authorization": "Bearer chave-de-teste-do-rui-0123456789",
            },
            json=INITIALIZE,
        ).status_code
        == 200
    )
    with patch.dict(app.os.environ, {"MCP_TESTERS": ""}):
        assert (
            client.post("/mcp", headers=CABECALHOS, json=INITIALIZE).status_code == 503
        )
    with patch.dict(app.os.environ, {"MCP_TESTERS": "isto não é json"}):
        assert (
            client.post("/mcp", headers=CABECALHOS, json=INITIALIZE).status_code == 503
        )
    # Rotas fora de /mcp não exigem chave.
    assert (
        client.get("/api/health").status_code == 200
        and client.get("/").status_code == 200
    )
    assert client.get("/xyz").status_code == 404
    eventos = [json.loads(l) for l in log.getvalue().splitlines() if l.startswith("{")]
    motivos = {e["motivo"] for e in eventos if e["event"] == "mcp_acesso_negado"}
    assert motivos == {"sem_chave", "chave_invalida", "testers_por_configurar"}, motivos
    assert all(
        e.get("request_id") for e in eventos if e["event"] == "mcp_acesso_negado"
    )
    assert "chave-de-teste" not in log.getvalue() and "Bearer" not in log.getvalue()


def main():
    log = io.StringIO()
    handlers = app.logger.handlers[:]
    app.logger.handlers = [logging.StreamHandler(log)]
    try:
        correr(log)
    finally:
        app.logger.handlers = handlers


class Resposta:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return b'{"result": "1-0"}'


class UpstashFalsa:
    """Substitui build_opener: guarda os pedidos em vez de os enviar para a Upstash real."""

    def __init__(self):
        self.pedidos = []
        self.falhar = False

    def __call__(self, *handlers):
        return SimpleNamespace(open=self.open)

    def open(self, request, timeout):
        assert timeout == 1.5
        if self.falhar:
            raise OSError("upstash em baixo")
        self.pedidos.append(request)
        return Resposta()

    def ultimo_comando(self):
        return json.loads(self.pedidos[-1].data)


def campos(comando):
    assert comando[:6] == [
        "XADD",
        "entrelinhas:mcp:chamadas",
        "MAXLEN",
        "~",
        "10000",
        "*",
    ], comando
    pares = comando[6:]
    return dict(zip(pares[::2], pares[1::2]))


def testar_log_upstash(client, log, upstash):
    from datetime import datetime

    with patch.object(app, "OpenAI", return_value=resposta_fake("Tarefa.")):
        chamar(client, "Comprar pão")
    pedido = upstash.pedidos[-1]
    assert (
        pedido.full_url == "https://teste.upstash.io" and pedido.get_method() == "POST"
    )
    assert pedido.headers["Authorization"] == "Bearer token-upstash-teste"
    c = campos(upstash.ultimo_comando())
    assert (
        c["tester"] == "ana" and c["categoria"] == "tarefa" and c["estado"] == "ok"
    ), c
    assert datetime.fromisoformat(c["hora"]).utcoffset().total_seconds() == 0
    assert "Comprar pão" not in pedido.data.decode()  # o texto da nota nunca sai

    # O tester vem da chave usada: com a chave do Rui, o log diz rui.
    with patch.object(app, "OpenAI", return_value=resposta_fake("ideia")):
        client.post(
            "/mcp",
            headers={
                **CABECALHOS,
                "Authorization": "Bearer chave-de-teste-do-rui-0123456789",
            },
            json={
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {
                    "name": "classificar_nota",
                    "arguments": {"texto": "Uma app para relógios"},
                },
            },
        )
    assert campos(upstash.ultimo_comando())["tester"] == "rui"

    # Chamada falhada também é registada, sem categoria.
    with patch.object(app, "OpenAI", return_value=resposta_fake("E")):
        chamar(client, "nota privada de teste")
    c = campos(upstash.ultimo_comando())
    assert c["estado"] == "erro" and c["categoria"] == "" and c["tester"] == "ana", c

    # Upstash em baixo: a tool responde na mesma e fica só um aviso.
    upstash.falhar = True
    with patch.object(app, "OpenAI", return_value=resposta_fake("agenda")):
        r = chamar(client, "Dentista às 10h")
    upstash.falhar = False
    assert r["structuredContent"] == {"categoria": "agenda"}, r
    assert '"upstash_envio_falhou"' in log.getvalue() and '"OSError"' in log.getvalue()

    # URL que não é da Upstash ou configuração em falta: nada é enviado.
    total = len(upstash.pedidos)
    for env, evento in (
        (
            {"UPSTASH_REDIS_REST_URL": "https://attacker.example"},
            "upstash_configuracao_invalida",
        ),
        (
            {"UPSTASH_REDIS_REST_URL": "http://teste.upstash.io"},
            "upstash_configuracao_invalida",
        ),
        ({"UPSTASH_REDIS_REST_TOKEN": ""}, "upstash_por_configurar"),
    ):
        with (
            patch.dict(app.os.environ, env),
            patch.object(app, "OpenAI", return_value=resposta_fake("tarefa")),
        ):
            assert chamar(client, "Comprar pão")["structuredContent"] == {
                "categoria": "tarefa"
            }
        assert f'"{evento}"' in log.getvalue(), evento
    assert len(upstash.pedidos) == total
    assert "token-upstash-teste" not in log.getvalue()


def correr(log):
    upstash = UpstashFalsa()
    ambiente = {
        "NVIDIA_API_KEY": "chave-de-teste",
        "MCP_TESTERS": TESTERS,
        "UPSTASH_REDIS_REST_URL": "https://teste.upstash.io",
        "UPSTASH_REDIS_REST_TOKEN": "token-upstash-teste",
    }
    with (
        TestClient(app.app) as client,
        patch.dict(app.os.environ, ambiente),
        patch.object(app, "build_opener", upstash),
    ):
        testar_chaves(client, log)
        testar_log_upstash(client, log, upstash)
        rpc(client, "initialize", INITIALIZE["params"])

        tools = rpc(client, "tools/list")["result"]["tools"]
        assert [t["name"] for t in tools] == ["classificar_nota"]
        tool = tools[0]
        assert tool["inputSchema"]["required"] == ["texto"]
        assert "categoria" in tool["outputSchema"]["properties"]

        with patch.object(app, "OpenAI", return_value=resposta_fake("Tarefa.")):
            r = chamar(client, "Comprar pão")
            assert not r.get("isError") and r["structuredContent"] == {
                "categoria": "tarefa"
            }, r

        with patch.object(app, "OpenAI", return_value=resposta_fake("E")):
            r = chamar(client, "nota privada de teste")
            assert r["isError"] and "categoria válida" in r["content"][0]["text"], r

        r = chamar(client, "   ")
        assert r["isError"] and "Escreve uma nota" in r["content"][0]["text"], r

        r = chamar(client, "x" * 4001)
        assert r["isError"], r

        with patch.dict(app.os.environ, {"NVIDIA_API_KEY": ""}):
            r = chamar(client, "Comprar pão")
            assert r["isError"] and "NVIDIA" in r["content"][0]["text"], r

        print(
            "OK: sem chave/chave errada/esquema errado/chave curta → 401; sem testers → 503; "
            "rotas fora de /mcp abertas; logs sem chaves."
        )
        print(
            "OK: cada chamada → XADD com tester (da chave), categoria, estado e hora UTC; erros registados; "
            "Upstash em baixo não afeta a tool; URL inválido/config em falta → nada enviado; sem texto nem tokens."
        )
        print(
            'OK: tools/list expõe classificar_nota; sucesso → {"categoria": "tarefa"}; '
            "categoria inválida, texto vazio, texto longo e chave em falta → isError."
        )
        print("Exemplo:", json.dumps(tool, ensure_ascii=False)[:300], "...")


if __name__ == "__main__":
    main()
