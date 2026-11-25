"""Valida o conjunto sintético equilibrado da R7.1 sem rede nem chaves."""

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "eval" / "r71_dados_sinteticos.jsonl"
CONFIG = Path(__file__).resolve().parent / "classificador_config.json"


def main() -> None:
    configuracao = json.loads(CONFIG.read_text(encoding="utf-8"))
    categorias = set(configuracao["DEFINICOES"])
    notas = [
        json.loads(linha)
        for linha in DATASET.read_text(encoding="utf-8").splitlines()
        if linha.strip()
    ]

    assert len(notas) == 200, f"Esperadas 200 notas, encontradas {len(notas)}."
    assert all(set(nota) == {"texto", "categoria"} for nota in notas)
    assert all(
        isinstance(nota["texto"], str) and nota["texto"].strip() for nota in notas
    )
    assert all(nota["categoria"] in categorias for nota in notas)
    assert Counter(nota["categoria"] for nota in notas) == {
        categoria: 20 for categoria in categorias
    }
    textos = [nota["texto"].strip().casefold() for nota in notas]
    assert len(set(textos)) == len(textos), "Há textos duplicados no conjunto."

    print("OK: 200 notas únicas, 20 por categoria, estrutura e etiquetas válidas.")


if __name__ == "__main__":
    main()
