"""Testes offline da avaliação R4.4."""

import contextlib
import io
import json
from types import SimpleNamespace
from unittest.mock import patch

import app
import avaliar


def main():
    golden = avaliar.carregar_golden()
    assert len(golden) == 34
    assert {item["categoria"] for item in golden} == set(app.CATEGORIES)
    assert avaliar.percentil([1, 2, 3, 4, 5], 50) == 3
    assert avaliar.percentil([1, 2, 3, 4, 5], 95) == 5

    def modelo(texto, request_id, origem, recolher_tokens):
        recolher_tokens(10, 2)
        return "tarefa"

    output = io.StringIO()
    with (
        patch.object(app, "classificar_texto", side_effect=modelo),
        contextlib.redirect_stdout(output),
    ):
        avaliar.avaliar([{"texto": "Exemplo sintético", "categoria": "tarefa"}], 3)
    resultado = output.getvalue()
    assert "100.00% ± 0.00%" in resultado
    assert "entrada 10.00; saída 2.00" in resultado
    assert "Tokens disponíveis: 3/3" in resultado

    resposta = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps({"categoria": "tarefa"}))
            )
        ],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3),
    )
    cliente = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: resposta)
        )
    )
    tokens = []
    with (
        patch.dict(app.os.environ, {"NVIDIA_API_KEY": "chave-ficticia"}),
        patch.object(app, "OpenAI", return_value=cliente),
        patch.object(app, "log_event"),
    ):
        categoria = app.classificar_texto(
            "Nota de teste", "id", "avaliacao", lambda a, b: tokens.append((a, b))
        )
    assert categoria == "tarefa" and tokens == [(12, 3)]

    def falha(texto, request_id, origem, recolher_tokens):
        raise app.ErroClassificacao(502, "erro")

    with (
        patch.object(app, "classificar_texto", side_effect=falha),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        try:
            avaliar.avaliar([{"texto": "Exemplo sintético", "categoria": "tarefa"}], 1)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Uma falha não pode produzir uma baseline válida")
    print("OK: golden, percentis, métricas e falhas da avaliação R4.4.")


if __name__ == "__main__":
    main()
