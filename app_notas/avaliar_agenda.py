"""Avalia o extrator de eventos de agenda contra o golden de 10 notas.

Este script faz chamadas reais ao endpoint NVIDIA e requer NVIDIA_API_KEY.
As notas do golden são sintéticas; não usar aqui notas privadas de utilizadores.
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from agenda_evento import extrair_evento_agenda

ROOT = Path(__file__).resolve().parent
INTERVALO_SEGUNDOS = 12
ESPERA_RATE_LIMIT_SEGUNDOS = 60


def carregar_exemplos() -> list[dict]:
    caminho = ROOT.parent / "eval" / "agenda.jsonl"
    return [
        json.loads(linha)
        for linha in caminho.read_text(encoding="utf-8").splitlines()
        if linha.strip()
    ]


def avaliar() -> int:
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT.parent / ".env")
    if not os.environ.get("NVIDIA_API_KEY"):
        print("Erro: define NVIDIA_API_KEY em app_notas/.env ou no ambiente.")
        return 1

    exemplos = carregar_exemplos()
    if len(exemplos) != 10:
        print(f"Erro: o golden deve ter 10 notas; foram encontradas {len(exemplos)}.")
        return 1

    acertos = 0
    erros_tecnicos = 0
    for indice, exemplo in enumerate(exemplos, 1):
        referencia = datetime.fromisoformat(exemplo["referencia"])
        resultado = None
        for tentativa in range(3):
            resultado = extrair_evento_agenda(exemplo["texto"], referencia)
            if resultado.estado != "limite_modelo" or tentativa == 2:
                break
            print(
                f"{indice}: limite temporário; nova tentativa em "
                f"{ESPERA_RATE_LIMIT_SEGUNDOS}s.",
                flush=True,
            )
            time.sleep(ESPERA_RATE_LIMIT_SEGUNDOS)

        assert resultado is not None
        obtido = resultado.quando
        certo = obtido == exemplo["esperado"]
        acertos += certo
        erros_tecnicos += resultado.estado in {
            "chave_em_falta",
            "resposta_invalida",
            "limite_modelo",
        }
        erros_tecnicos += resultado.estado.startswith("erro_modelo_")
        print(
            f"{indice}: {'OK' if certo else 'ERRO'} "
            f"estado={resultado.estado} esperado={exemplo['esperado']} obtido={obtido}",
            flush=True,
        )
        if indice < len(exemplos):
            time.sleep(INTERVALO_SEGUNDOS)

    print(
        f"Resultado: {acertos}/{len(exemplos)}; "
        f"erros técnicos={erros_tecnicos}; critério=10 notas e pelo menos 8 acertos."
    )
    return 0 if acertos >= 8 and erros_tecnicos == 0 else 1


if __name__ == "__main__":
    sys.exit(avaliar())
