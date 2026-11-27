"""R9.1: métricas por chamada sem chave, rede ou notas de produção."""

import json
import os
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from openai import OpenAIError

temp_dir = tempfile.TemporaryDirectory()
os.environ["NOTAS_SQLITE"] = str(Path(temp_dir.name) / "notas.db")

import agenda_evento  # noqa: E402
import app  # noqa: E402
import db  # noqa: E402
from metricas_modelo import medir_chamada_modelo  # noqa: E402

os.environ.pop("DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
assert not db.url_postgres(), "o teste não pode usar Postgres de produção"


def resposta_modelo(conteudo: str, entrada: int, saida: int):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=conteudo, tool_calls=None))
        ],
        usage=SimpleNamespace(prompt_tokens=entrada, completion_tokens=saida),
    )


class ClienteFalso:
    def __init__(self, *respostas):
        self.respostas = iter(respostas)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.criar))

    def criar(self, **_kwargs):
        return next(self.respostas)


def testar_chamadas_da_aplicacao():
    eventos: list[dict] = []
    utilizador = str(uuid.uuid4())
    nota = "Consulta privada em 02/12/2026 às 09:40"
    segredo = "chave-falsa-r91"

    def guardar(registo, _nivel):
        eventos.append(registo)

    with (
        patch.dict(os.environ, {"NVIDIA_API_KEY": segredo}),
        patch.object(app, "enviar_loki", side_effect=guardar),
        patch.object(
            app,
            "OpenAI",
            return_value=ClienteFalso(
                resposta_modelo('{"categoria":"agenda"}', 120, 4)
            ),
        ),
        patch.object(
            agenda_evento,
            "OpenAI",
            return_value=ClienteFalso(resposta_modelo("{}", 220, 16)),
        ),
        TestClient(app.app) as client,
    ):
        resposta = client.post(
            "/api/notas",
            json={"texto": nota},
            headers={"X-Utilizador": utilizador},
        )
    assert resposta.status_code == 201, resposta.text
    metricas = [e for e in eventos if e["event"] == "chamada_modelo"]
    assert len(metricas) == 2
    assert [e["etapa"] for e in metricas] == ["classificacao", "agenda"]
    assert [(e["tokens_entrada"], e["tokens_saida"]) for e in metricas] == [
        (120, 4),
        (220, 16),
    ]
    assert all(e["request_id"] == resposta.headers["X-Request-ID"] for e in metricas)
    assert all(e["modelo"] == app.MODEL and e["duracao_ms"] >= 0 for e in metricas)
    assert all(e["estado"] == "ok" and e["origem"] == "http" for e in metricas)
    registos = json.dumps(eventos, ensure_ascii=False)
    assert (
        nota not in registos and segredo not in registos and utilizador not in registos
    )

    eventos.clear()
    with (
        patch.dict(os.environ, {"NVIDIA_API_KEY": segredo}),
        patch.object(app, "enviar_loki", side_effect=guardar),
        patch.object(
            app,
            "OpenAI",
            return_value=ClienteFalso(
                resposta_modelo("Primeira resposta", 50, 8),
                resposta_modelo("Segunda resposta", 70, 12),
            ),
        ),
    ):
        app.chamar_modelo_agente([], "pedido-agente")
        app.chamar_modelo_agente([], "pedido-agente")
    metricas = [e for e in eventos if e["event"] == "chamada_modelo"]
    assert len(metricas) == 2
    assert all(
        e["etapa"] == "agente" and e["request_id"] == "pedido-agente" for e in metricas
    )
    assert [e["tokens_entrada"] for e in metricas] == [50, 70]
    assert "Primeira resposta" not in json.dumps(eventos, ensure_ascii=False)

    eventos.clear()
    with (
        patch.dict(os.environ, {"NVIDIA_API_KEY": segredo}),
        patch.object(app, "enviar_loki", side_effect=guardar),
        patch.object(
            app,
            "OpenAI",
            return_value=ClienteFalso(resposta_modelo('{"categoria":"tarefa"}', 80, 3)),
        ),
    ):
        assert app.classificar_texto("Nota MCP", "pedido-mcp", origem="mcp") == "tarefa"
    metrica = next(e for e in eventos if e["event"] == "chamada_modelo")
    assert metrica["origem"] == "mcp" and metrica["etapa"] == "classificacao"

    eventos.clear()

    def falhar_modelo(**_kwargs):
        raise OpenAIError("texto privado que não pode ser registado")

    cliente_com_erro = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=falhar_modelo))
    )
    with (
        patch.dict(os.environ, {"NVIDIA_API_KEY": segredo}),
        patch.object(app, "enviar_loki", side_effect=guardar),
        patch.object(app, "OpenAI", return_value=cliente_com_erro),
    ):
        try:
            app.classificar_texto("Outra nota privada", "pedido-falha", origem="http")
        except app.ErroClassificacao as exc:
            assert exc.status == 502
        else:
            raise AssertionError("A falha do fornecedor deve manter a resposta 502.")
    metrica = next(e for e in eventos if e["event"] == "chamada_modelo")
    assert metrica["estado"] == "erro" and metrica["tipo_erro"] == "OpenAIError"
    assert "tokens_entrada" not in metrica and "tokens_saida" not in metrica
    assert "texto privado" not in json.dumps(eventos, ensure_ascii=False)


def testar_falha_e_usage_em_falta():
    registos: list[dict] = []

    def registar(_nivel, evento, **campos):
        registos.append({"event": evento, **campos})

    medir_chamada_modelo(
        lambda: SimpleNamespace(usage=None),
        modelo="modelo-teste",
        etapa="classificacao",
        origem="http",
        request_id="sem-usage",
        registar=registar,
    )
    assert "tokens_entrada" not in registos[0] and "tokens_saida" not in registos[0]

    def falhar():
        raise ValueError("texto privado que não pode ser registado")

    try:
        medir_chamada_modelo(
            falhar,
            modelo="modelo-teste",
            etapa="agente",
            origem="http",
            request_id="falha",
            registar=registar,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("A falha original deve ser propagada.")
    assert registos[1]["estado"] == "erro"
    assert registos[1]["tipo_erro"] == "ValueError"
    assert "tokens_entrada" not in registos[1]
    assert "texto privado" not in json.dumps(registos, ensure_ascii=False)


def testar_loki_indisponivel():
    def falhar_envio(*_args, **_kwargs):
        raise OSError("falha de rede simulada")

    cliente = ClienteFalso(resposta_modelo('{"categoria":"tarefa"}', 15, 2))
    with (
        patch.dict(
            os.environ,
            {
                "NVIDIA_API_KEY": "chave-falsa-r91",
                "LOKI_PUSH_URL": "https://logs-test.grafana.net/loki/api/v1/push",
                "LOKI_USER": "123",
                "LOKI_TOKEN": "token-teste",
            },
        ),
        patch.object(app, "OpenAI", return_value=cliente),
        patch.object(
            app,
            "build_opener",
            return_value=SimpleNamespace(open=falhar_envio),
        ),
    ):
        assert (
            app.classificar_texto("Nota sem dados reais", "loki-falhou", origem="http")
            == "tarefa"
        )


def testar_dashboard():
    caminho = Path(__file__).resolve().parent / "grafana" / "dashboard.json"
    dashboard = json.loads(caminho.read_text(encoding="utf-8"))
    painel_latencia = next(p for p in dashboard["panels"] if p["id"] == 4)
    painel_tokens = next(p for p in dashboard["panels"] if p["id"] == 5)
    assert all(
        "quantile_over_time" in alvo["expr"]
        and 'event="chamada_modelo"' in alvo["expr"]
        and "unwrap duracao_ms" in alvo["expr"]
        for alvo in painel_latencia["targets"]
    )
    assert {alvo["legendFormat"] for alvo in painel_latencia["targets"]} == {
        "p50",
        "p95",
    }
    assert all("sum_over_time" in alvo["expr"] for alvo in painel_tokens["targets"])
    assert {alvo["legendFormat"] for alvo in painel_tokens["targets"]} == {
        "Entrada",
        "Saída",
    }


def main():
    try:
        testar_chamadas_da_aplicacao()
        testar_falha_e_usage_em_falta()
        testar_loki_indisponivel()
        testar_dashboard()
        print("OK: métricas por chamada, erros, privacidade, MCP e painéis Grafana.")
    finally:
        temp_dir.cleanup()


if __name__ == "__main__":
    main()
