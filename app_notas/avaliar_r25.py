"""Avalia R2.5 com o modelo real em dados sintéticos e, se pedido, no golden."""

import argparse
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent
PEDIDOS = (
    ("criar_direto", "Cria a categoria compras", "compras"),
    ("categoria_chamada", "Quero uma categoria chamada livros", "livros"),
    ("adicionar", "Adiciona uma categoria viagens", "viagens"),
)
NOTAS_COMPRAS = (
    "Lista de compras: leite, arroz e farinha.",
    "Nas compras da semana, prefiro comparar preços entre supermercados.",
    "Os recibos das compras de novembro estão na pasta verde.",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden",
        action="store_true",
        help="Envia as 34 notas do golden à NVIDIA; requer autorização para estes dados.",
    )
    args = parser.parse_args()
    if not os.environ.get("NVIDIA_API_KEY"):
        print("Configure NVIDIA_API_KEY para a avaliação real.", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as pasta:
        os.environ["NOTAS_SQLITE"] = str(Path(pasta) / "avaliacao.db")
        import app
        import categorias
        import db

        # app.py pode carregar um .env; esta avaliação nunca escreve em Postgres.
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("POSTGRES_URL", None)
        if db.url_postgres() or db.SQLITE_PATH != Path(os.environ["NOTAS_SQLITE"]):
            raise RuntimeError("A avaliação precisa de SQLite temporário.")

        with TestClient(app.app) as client:
            propostas = 0
            for identificador, mensagem, nome in PEDIDOS:
                utilizador = str(uuid.uuid4())
                resposta = client.post(
                    "/api/agente",
                    headers={"X-Utilizador": utilizador},
                    json={"mensagem": mensagem},
                )
                pendente = (
                    resposta.json().get("pendente")
                    if resposta.status_code == 200
                    else None
                )
                correto = (
                    pendente is not None
                    and pendente.get("nome") == nome
                    and nome not in categorias.opcoes(utilizador)
                )
                propostas += int(correto)
                print(f"Pedido {identificador}: proposta correta={correto}")

            utilizador_compras = str(uuid.uuid4())
            proposta = categorias.propor(utilizador_compras, "compras")
            aprovado = client.post(
                f"/api/categorias/{proposta['id']}/aprovar",
                headers={"X-Utilizador": utilizador_compras},
            )
            if aprovado.status_code != 200:
                raise RuntimeError("Não foi possível preparar a categoria de teste.")
            escolhas_compras: dict[str, int] = {}
            for nota in NOTAS_COMPRAS:
                categoria = app.classificar_texto(
                    nota, "avaliacao-r25", "avaliacao", utilizador=utilizador_compras
                )
                escolhas_compras[categoria] = escolhas_compras.get(categoria, 0) + 1

            print(f"Pedidos ao agente com proposta correta: {propostas}/{len(PEDIDOS)}")
            print(
                f"Notas de compras: {json.dumps(escolhas_compras, ensure_ascii=False)}"
            )
            if args.golden:
                golden = json.loads((ROOT / "golden.json").read_text(encoding="utf-8"))
                utilizador_base = str(uuid.uuid4())
                acertos = entrada = saida = 0

                def contar_tokens(prompt: int | None, resposta: int | None) -> None:
                    nonlocal entrada, saida
                    entrada += prompt or 0
                    saida += resposta or 0

                for item in golden:
                    categoria = app.classificar_texto(
                        item["texto"],
                        "avaliacao-r25",
                        "avaliacao",
                        recolher_tokens=contar_tokens,
                        utilizador=utilizador_base,
                    )
                    acertos += categoria == item["categoria"]
                print(
                    f"Golden oficial: {acertos}/{len(golden)}; tokens: {entrada}+{saida}"
                )
            return 0 if propostas == len(PEDIDOS) else 1


if __name__ == "__main__":
    sys.exit(main())
