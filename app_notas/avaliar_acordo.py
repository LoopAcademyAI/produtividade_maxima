"""Mede o acordo de cinco votos no golden oficial, sem imprimir notas."""

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from openai import OpenAI, OpenAIError, RateLimitError

import app
from avaliar import GOLDEN, carregar_golden

ROOT = Path(__file__).resolve().parent
ESTADO = ROOT / ".r42-votos.json"
RESULTADOS = ROOT.parent / "eval" / "r42_resultados.json"
TEMPERATURA = 0.8
NUM_VOTOS = 5


def novo_estado(notas: list[dict[str, str]], digest: str) -> dict[str, Any]:
    return {
        "golden_sha256": digest,
        "modelo": app.MODEL,
        "temperatura": TEMPERATURA,
        "votos_por_nota": NUM_VOTOS,
        "votos": [[] for _ in notas],
    }


def carregar_estado(
    caminho: Path, notas: list[dict[str, str]], digest: str
) -> dict[str, Any]:
    if not caminho.exists():
        return novo_estado(notas, digest)
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if (
        not isinstance(dados, dict)
        or dados.get("golden_sha256") != digest
        or dados.get("modelo") != app.MODEL
        or dados.get("temperatura") != TEMPERATURA
        or dados.get("votos_por_nota") != NUM_VOTOS
        or not isinstance(dados.get("votos"), list)
        or len(dados["votos"]) != len(notas)
        or any(
            not isinstance(votos, list)
            or len(votos) > NUM_VOTOS
            or any(voto not in app.CATEGORIES for voto in votos)
            for votos in dados["votos"]
        )
    ):
        raise ValueError("Estado incompatível com o golden, modelo ou parâmetros.")
    return dados


def guardar_estado(caminho: Path, dados: dict[str, Any]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(caminho.name + ".tmp")
    temporario.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporario.replace(caminho)


def classificar_amostra(cliente: OpenAI, texto: str) -> str:
    resposta = cliente.chat.completions.create(
        model=app.MODEL,
        messages=[
            {"role": "system", "content": app.criar_instrucoes_sistema()},
            {"role": "user", "content": app.criar_prompt(texto)},
        ],
        temperature=TEMPERATURA,
        max_tokens=512,
        response_format=app.FORMATO_CATEGORIA,  # type: ignore[arg-type]
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    escolhas = getattr(resposta, "choices", None)
    mensagem = getattr(escolhas[0], "message", None) if escolhas else None
    conteudo = getattr(mensagem, "content", None)
    categoria = (
        app.extrair_categoria_json(conteudo) if isinstance(conteudo, str) else None
    )
    if categoria is None:
        raise ValueError("Resposta do modelo fora do schema.")
    return categoria


def recolher_votos(
    notas: list[dict[str, str]],
    estado: dict[str, Any],
    caminho: Path,
    classificar: Callable[[str], str],
    intervalo: float,
    esperar: Callable[[float], None] = time.sleep,
) -> None:
    for indice, nota in enumerate(notas):
        votos = estado["votos"][indice]
        while len(votos) < NUM_VOTOS:
            categoria = classificar(nota["texto"])
            if categoria not in app.CATEGORIES:
                raise ValueError("O classificador devolveu uma categoria inválida.")
            votos.append(categoria)
            guardar_estado(caminho, estado)
            print(
                f"Nota {indice + 1}/{len(notas)}, voto {len(votos)}/{NUM_VOTOS}: {categoria}",
                flush=True,
            )
            if intervalo > 0:
                esperar(intervalo)


def apurar(votos: list[str], esperado: str) -> tuple[str | None, int, bool]:
    if len(votos) != NUM_VOTOS or any(voto not in app.CATEGORIES for voto in votos):
        raise ValueError("São necessários cinco votos válidos por nota.")
    contagens = Counter(votos)
    maximo = max(contagens.values())
    vencedores = [categoria for categoria, n in contagens.items() if n == maximo]
    vencedora = vencedores[0] if len(vencedores) == 1 else None
    return vencedora, maximo, vencedora == esperado


def relatorio(notas: list[dict[str, str]], estado: dict[str, Any]) -> str:
    linhas = [
        "| Nota | Esperado | Votos | Votada | Acordo | Acertou? |",
        "| ---: | --- | --- | --- | ---: | --- |",
    ]
    resumo: dict[int, list[int]] = {n: [0, 0, 0] for n in range(1, NUM_VOTOS + 1)}
    for indice, nota in enumerate(notas):
        votos = estado["votos"][indice]
        vencedora, n, acertou = apurar(votos, nota["categoria"])
        contagens = Counter(votos)
        distribuicao = ", ".join(
            f"{categoria}×{quantidade}"
            for categoria, quantidade in sorted(contagens.items())
        )
        situacao = "sim" if acertou else "não" if vencedora else "empate"
        resumo[n][0 if acertou else 1 if vencedora else 2] += 1
        linhas.append(
            f"| {indice + 1} | {nota['categoria']} | {distribuicao} | "
            f"{vencedora or '—'} | {n}/5 ({n * 20}%) | {situacao} |"
        )
    linhas.extend(
        [
            "",
            "| Acordo | Certas | Erradas | Empates |",
            "| ---: | ---: | ---: | ---: |",
        ]
    )
    for n, (certas, erradas, empates) in resumo.items():
        if certas + erradas + empates:
            linhas.append(f"| {n}/5 ({n * 20}%) | {certas} | {erradas} | {empates} |")
    return "\n".join(linhas)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--estado", type=Path, default=ESTADO)
    parser.add_argument("--intervalo", type=float, default=1.0)
    parser.add_argument("--apenas-relatorio", action="store_true")
    args = parser.parse_args()
    try:
        if args.intervalo < 0:
            raise ValueError("O intervalo não pode ser negativo.")
        notas = carregar_golden()
        digest = hashlib.sha256(GOLDEN.read_bytes()).hexdigest()
        origem = (
            RESULTADOS
            if args.apenas_relatorio and not args.estado.exists()
            else args.estado
        )
        estado = carregar_estado(origem, notas, digest)
        completos = all(len(votos) == NUM_VOTOS for votos in estado["votos"])
        if not completos and not args.apenas_relatorio:
            chave = os.environ.get("NVIDIA_API_KEY")
            if not chave:
                raise ValueError("Configure NVIDIA_API_KEY antes da avaliação real.")
            cliente = OpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=chave,
                timeout=30,
                max_retries=1,
            )
            recolher_votos(
                notas,
                estado,
                args.estado,
                lambda texto: classificar_amostra(cliente, texto),
                args.intervalo,
            )
        if not all(len(votos) == NUM_VOTOS for votos in estado["votos"]):
            raise ValueError("Avaliação incompleta; retoma com o mesmo comando.")
        if not args.apenas_relatorio:
            guardar_estado(RESULTADOS, estado)
        print(f"Golden SHA-256: {digest}; modelo: {app.MODEL}; T={TEMPERATURA}")
        print(relatorio(notas, estado))
        if args.apenas_relatorio:
            print(f"Resultados lidos de {origem}")
        else:
            print(f"Resultados completos guardados em {RESULTADOS}")
        return 0
    except RateLimitError:
        print(
            "HTTP 429: votos já obtidos guardados; retoma quando houver quota.",
            file=sys.stderr,
        )
    except (OpenAIError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            f"Avaliação incompleta ({type(exc).__name__}); verifica o estado e retoma.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
