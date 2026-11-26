"""Avaliação real da R2.4b com o modelo (requer rede e NVIDIA_API_KEY).

Carrega as 34 notas do golden num SQLite temporário, faz as perguntas de aceitação ao
/api/agente e imprime só resultados: nunca o texto das notas.

    uv run python avaliar_r24b.py --corridas 3
"""

import argparse
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

os.environ["NOTAS_SQLITE"] = os.path.join(tempfile.mkdtemp(), "avaliacao.db")
import app  # noqa: E402  (carrega o .env: NVIDIA_API_KEY e talvez DATABASE_URL)
import db  # noqa: E402
import ferramentas  # noqa: E402

os.environ.pop("DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
assert not db.url_postgres(), "a avaliação nunca pode usar a base de dados de produção"

GOLDEN = json.loads(
    (Path(__file__).resolve().parent / "golden.json").read_text(encoding="utf-8")
)
# Uma palavra de cada tarefa do golden, para ver se a resposta a menciona.
PALAVRAS_TAREFAS = ("vitamina", "compras", "carregador", "pilhas", "#42")


def perguntar(client, utilizador, mensagem):
    """Devolve (resposta, ferramentas chamadas, notas devolvidas pelas ferramentas)."""
    notas: list[dict] = []
    executar = ferramentas.executar

    def executar_e_registar(nome, utilizador_, args):
        conteudo = executar(nome, utilizador_, args)
        if not conteudo.startswith("Erro"):
            notas.extend(json.loads(conteudo)["notas"])
        return conteudo

    with patch.object(ferramentas, "executar", side_effect=executar_e_registar):
        r = client.post(
            "/api/agente",
            headers={"X-Utilizador": utilizador},
            json={"mensagem": mensagem},
        )
    if r.status_code != 200:
        return f"HTTP {r.status_code}", [], notas
    corpo = r.json()
    return corpo["resposta"], [f["nome"] for f in corpo["ferramentas"]], notas


def corrida(client, ana, novo):
    resultados = {}

    resposta, chamadas, notas = perguntar(client, ana, "O que tenho para fazer?")
    texto = resposta.lower()
    resultados["tarefas: usa listar_notas"] = "listar_notas" in chamadas
    resultados["tarefas: só notas 'tarefa'"] = bool(notas) and all(
        n["categoria"] == "tarefa" for n in notas
    )
    resultados["tarefas: menciona as 5"] = all(p in texto for p in PALAVRAS_TAREFAS)

    resposta, chamadas, notas = perguntar(
        client, ana, "Tenho alguma coisa com a Sofia?"
    )
    resultados["sofia: usa procurar_notas"] = "procurar_notas" in chamadas
    resultados["sofia: encontra a nota"] = any(
        "sofia" in n["texto"].lower() for n in notas
    ) and ("sofia" in resposta.lower())

    vistos = []
    for mensagem in ("O que tenho para fazer?", "Tenho alguma coisa com a Sofia?"):
        resposta, _, notas = perguntar(client, novo, mensagem)
        vistos.extend(notas)
        vistos.extend(p for p in PALAVRAS_TAREFAS if p in resposta.lower())
    resultados["isolamento: outro utilizador não vê nada"] = not vistos
    return resultados


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corridas", type=int, default=3)
    corridas = parser.parse_args().corridas
    if not os.environ.get("NVIDIA_API_KEY"):
        print("Falta NVIDIA_API_KEY (no .env ou no ambiente).", file=sys.stderr)
        return 2

    ana, novo = str(uuid.uuid4()), str(uuid.uuid4())
    for nota in GOLDEN:
        db.criar(ana, nota["texto"], nota["categoria"])

    totais: dict[str, int] = {}
    with TestClient(app.app) as client:
        for i in range(corridas):
            for criterio, ok in corrida(client, ana, novo).items():
                totais[criterio] = totais.get(criterio, 0) + ok
            print(f"Corrida {i + 1}/{corridas} concluída.", file=sys.stderr)

    print(f"\nR2.4b · {len(GOLDEN)} notas do golden · {corridas} corridas")
    for criterio, n in totais.items():
        print(f"  {'OK ' if n == corridas else 'FALHA'}  {criterio}: {n}/{corridas}")
    return 0 if all(n == corridas for n in totais.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
