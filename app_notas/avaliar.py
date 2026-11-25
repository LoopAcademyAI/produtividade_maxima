"""Avalia o classificador da aplicação no golden da equipa."""

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import app

GOLDEN = Path(__file__).resolve().parent / "golden.json"


def carregar_golden(caminho: Path = GOLDEN) -> list[dict[str, str]]:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(dados, list) or len(dados) != 34:
        raise ValueError("O golden tem de conter exatamente 34 notas.")
    for item in dados:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("texto"), str)
            or not item["texto"].strip()
            or item.get("categoria") not in app.CATEGORIES
        ):
            raise ValueError("Nota ou categoria inválida no golden.")
    return dados


def percentil(valores: list[float], percentagem: float) -> float:
    """Percentil por nearest-rank, incluindo empates."""
    if not valores or not 0 < percentagem <= 100:
        raise ValueError("Percentil requer valores e percentagem entre 0 e 100.")
    return sorted(valores)[math.ceil(percentagem / 100 * len(valores)) - 1]


def avaliar(notas: list[dict[str, str]], corridas: int) -> None:
    if corridas < 1:
        raise ValueError("O número de corridas tem de ser positivo.")
    acertos = []
    latencias = []
    entradas = []
    saidas = []
    erros = []
    falhas = 0
    for corrida in range(1, corridas + 1):
        certos = 0
        for numero, nota in enumerate(notas, 1):
            tokens: list[tuple[int | None, int | None]] = []
            inicio = time.perf_counter()
            try:
                obtido = app.classificar_texto(
                    nota["texto"],
                    uuid4().hex,
                    "avaliacao",
                    lambda a, b: tokens.append((a, b)),
                )
            except app.ErroClassificacao:
                obtido = "erro de classificação"
                falhas += 1
            latencias.append(time.perf_counter() - inicio)
            if tokens and tokens[0][0] is not None and tokens[0][1] is not None:
                entradas.append(tokens[0][0])
                saidas.append(tokens[0][1])
            if obtido == nota["categoria"]:
                certos += 1
            else:
                erros.append(
                    (corrida, numero, nota["texto"], nota["categoria"], obtido)
                )
        acertos.append(100 * certos / len(notas))

    print(f"Modelo: {app.MODEL}; notas: {len(notas)}; corridas: {corridas}")
    print(
        f"Acerto médio: {statistics.mean(acertos):.2f}% ± {statistics.pstdev(acertos):.2f}% (desvio populacional)"
    )
    print(
        f"Latência: p50 {percentil(latencias, 50):.3f}s; p95 {percentil(latencias, 95):.3f}s (nearest-rank, incluindo falhas)"
    )
    print(f"Tokens disponíveis: {len(entradas)}/{len(latencias)} chamadas")
    if entradas:
        print(
            f"Tokens médios: entrada {statistics.mean(entradas):.2f}; saída {statistics.mean(saidas):.2f}"
        )
    else:
        print("Tokens médios: indisponíveis")
    print(f"Falhas de classificação: {falhas}")
    print("Erros no golden (corrida, nota, esperado, obtido):")
    for corrida, numero, texto, esperado, obtido in erros:
        print(f"{corrida}, {numero}: {texto} | {esperado} | {obtido}")
    if falhas or len(entradas) != len(latencias):
        raise RuntimeError(
            "Avaliação incompleta: falhas ou métricas de tokens em falta; não usar como baseline."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corridas", type=int, default=3)
    args = parser.parse_args()
    try:
        notas = carregar_golden()
        if not os.environ.get("NVIDIA_API_KEY"):
            raise ValueError("Configure NVIDIA_API_KEY para executar a avaliação real.")
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
        )
        print(
            f"Commit: {revision.stdout.strip() or 'indisponível'}; confirmar alterações locais antes de registar a baseline."
        )
        avaliar(notas, args.corridas)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
