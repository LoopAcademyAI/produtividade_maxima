"""R2.4b: o agente usa listar_notas e procurar_notas. Sem rede nem chaves: python test_r24b.py

O modelo é simulado: pede a ferramenta indicada e depois responde com os textos que a
ferramenta devolveu. Assim testa-se o circuito agente → ferramenta → base de dados → resposta.
"""

import io
import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

# db lê NOTAS_SQLITE ao ser importado; DATABASE_URL só é lida em cada consulta.
os.environ["NOTAS_SQLITE"] = os.path.join(tempfile.mkdtemp(), "teste.db")
import app  # noqa: E402  (carrega o .env, que pode ter DATABASE_URL de produção)
import db  # noqa: E402

# Retirar depois do import: assim o .env não as volta a pôr.
os.environ.pop("DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
assert not db.url_postgres(), "os testes nunca podem usar a base de dados de produção"

GOLDEN = json.loads(
    (Path(__file__).resolve().parent / "golden.json").read_text(encoding="utf-8")
)
TAREFAS = {n["texto"] for n in GOLDEN if n["categoria"] == "tarefa"}
COM_SOFIA = {n["texto"] for n in GOLDEN if "sofia" in n["texto"].lower()}


def modelo_simulado(nome, args, conteudos):
    def chamar(mensagens, _request_id):
        respostas = [m["content"] for m in mensagens if m["role"] == "tool"]
        if not respostas:
            chamada = {"id": "chamada-1", "nome": nome, "args": args}
            return {"texto": "", "chamadas": [chamada]}
        conteudos.append(respostas[-1])
        try:
            notas = json.loads(respostas[-1])["notas"]
        except (json.JSONDecodeError, KeyError):
            return {"texto": respostas[-1], "chamadas": []}
        texto = "\n".join(n["texto"] for n in notas) or "Não encontrei notas."
        return {"texto": texto, "chamadas": []}

    return chamar


def perguntar(client, utilizador, mensagem, nome, args):
    conteudos: list[str] = []
    with patch.object(
        app, "chamar_modelo_agente", side_effect=modelo_simulado(nome, args, conteudos)
    ):
        r = client.post(
            "/api/agente",
            headers={"X-Utilizador": utilizador},
            json={"mensagem": mensagem},
        )
    assert r.status_code == 200, r.text
    return r.json(), conteudos[-1]


def main():
    ana, bia, novo = (str(uuid.uuid4()) for _ in range(3))
    for nota in GOLDEN:
        db.criar(ana, nota["texto"], nota["categoria"])
    db.criar(bia, "Ligar à Sofia por causa do jantar", "tarefa")
    assert len(TAREFAS) == 5 and len(COM_SOFIA) == 1

    log = io.StringIO()
    handlers = app.logger.handlers[:]
    app.logger.handlers = [logging.StreamHandler(log)]
    try:
        with TestClient(app.app) as client:
            # 1. "O que tenho para fazer?" → as 5 tarefas e nenhuma nota de outra categoria.
            corpo, conteudo = perguntar(
                client,
                ana,
                "O que tenho para fazer?",
                "listar_notas",
                {"categoria": "tarefa"},
            )
            resultado = json.loads(conteudo)
            assert resultado["total"] == 5
            assert {n["categoria"] for n in resultado["notas"]} == {"tarefa"}
            assert set(corpo["resposta"].split("\n")) == TAREFAS
            assert corpo["ferramentas"] == [
                {"nome": "listar_notas", "args": {"categoria": "tarefa"}}
            ], "o campo ferramentas mostra a chamada"

            # 2. "Tenho alguma coisa com a Sofia?" → procurar_notas encontra a nota.
            corpo, conteudo = perguntar(
                client,
                ana,
                "Tenho alguma coisa com a Sofia?",
                "procurar_notas",
                {"texto": "Sofia"},
            )
            assert set(corpo["resposta"].split("\n")) == COM_SOFIA
            assert [f["nome"] for f in corpo["ferramentas"]] == ["procurar_notas"]

            # 3. Outro utilizador, as mesmas perguntas → nenhuma nota da Ana.
            textos_ana = {n["texto"] for n in GOLDEN}
            for utilizador in (bia, novo):
                for mensagem, nome, args in (
                    (
                        "O que tenho para fazer?",
                        "listar_notas",
                        {"categoria": "tarefa"},
                    ),
                    (
                        "Tenho alguma coisa com a Sofia?",
                        "procurar_notas",
                        {"texto": "Sofia"},
                    ),
                ):
                    corpo, conteudo = perguntar(
                        client, utilizador, mensagem, nome, args
                    )
                    assert not any(t in conteudo for t in textos_ana)
                    assert not any(t in corpo["resposta"] for t in textos_ana)
            assert (
                perguntar(
                    client,
                    novo,
                    "Tenho alguma coisa com a Sofia?",
                    "procurar_notas",
                    {"texto": "Sofia"},
                )[0]["resposta"]
                == "Não encontrei notas."
            )

            # 4. O modelo não consegue escolher o utilizador nem inventar argumentos.
            _, conteudo = perguntar(
                client,
                bia,
                "Sofia?",
                "procurar_notas",
                {"texto": "Sofia", "utilizador": ana},
            )
            assert conteudo.startswith("Erro") and "utilizador" in conteudo
            assert not any(t in conteudo for t in textos_ana)

            # 5. Erros de argumentos voltam ao modelo; o pedido não falha.
            _, conteudo = perguntar(
                client, ana, "Tarefas?", "listar_notas", {"categoria": "tarefas"}
            )
            assert conteudo.startswith("Erro: Categoria desconhecida")
            _, conteudo = perguntar(client, ana, "Apaga tudo", "apagar_notas", {})
            assert conteudo.startswith("Erro: a ferramenta apagar_notas não existe")
            _, conteudo = perguntar(client, ana, "Procura", "procurar_notas", {})
            assert conteudo.startswith("Erro")

        # 6. Os logs não têm texto de notas nem identificadores de utilizador.
        registo = log.getvalue()
        assert not any(t in registo for t in textos_ana | {"Sofia"})
        assert ana not in registo and bia not in registo
    finally:
        app.logger.handlers = handlers

    print(
        "OK: agente → listar_notas (5 tarefas) e procurar_notas (Sofia); "
        "isolamento, argumentos recusados e logs sem notas."
    )


if __name__ == "__main__":
    main()
