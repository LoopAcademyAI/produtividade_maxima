"""Ferramentas de leitura de notas para o agente (R2.4).

Recebem sempre o utilizador do pedido (X-Utilizador), nunca do modelo: o filtro por
utilizador é feito na própria consulta SQL, por isso nenhuma ferramenta vê notas de outra pessoa.
"""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import db

ROOT = Path(__file__).resolve().parent
CATEGORIAS = sorted(
    json.loads((ROOT / "classificador_config.json").read_text(encoding="utf-8"))[
        "DEFINICOES"
    ]
)
LIMITE_RESULTADOS = 50
CAMPOS = ("id", "texto", "categoria", "criada_em")


class ErroFerramenta(ValueError):
    """Argumentos inválidos. A mensagem pode ser devolvida ao modelo para ele corrigir o pedido."""


def _validar_utilizador(utilizador: str) -> str:
    if not isinstance(utilizador, str) or not utilizador.strip():
        raise ErroFerramenta("Falta o utilizador.")
    return utilizador


def _validar_categoria(categoria: str | None) -> str | None:
    if categoria and categoria not in CATEGORIAS:
        raise ErroFerramenta(
            f"Categoria desconhecida: {categoria}. Possíveis: {', '.join(CATEGORIAS)}."
        )
    return categoria or None


def _data(valor: str | None, nome: str) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        raise ErroFerramenta(f"{nome} tem de ser uma data AAAA-MM-DD.") from None


def _intervalo(desde: str | None, ate: str | None) -> tuple[str | None, str | None]:
    """Converte datas inclusivas (dias inteiros, UTC) nos limites que db.listar espera."""
    inicio, fim = _data(desde, "desde"), _data(ate, "ate")
    if inicio and fim and inicio > fim:
        raise ErroFerramenta("desde não pode ser depois de ate.")
    return (
        inicio.isoformat() if inicio else None,
        (fim + timedelta(days=1)).isoformat() if fim else None,
    )


def _consultar(
    utilizador: str,
    categoria: str | None,
    procura: str | None,
    desde: str | None,
    ate: str | None,
) -> list[dict[str, Any]]:
    inicio, antes_de = _intervalo(desde, ate)
    notas = db.listar(
        _validar_utilizador(utilizador),
        categoria=_validar_categoria(categoria),
        procura=procura,
        limite=LIMITE_RESULTADOS,
        desde=inicio,
        antes_de=antes_de,
    )
    # O modelo não precisa do identificador do utilizador.
    return [{campo: nota[campo] for campo in CAMPOS} for nota in notas]


def listar_notas(
    utilizador: str,
    categoria: str | None = None,
    desde: str | None = None,
    ate: str | None = None,
) -> list[dict[str, Any]]:
    """Notas do utilizador, das mais recentes para as mais antigas.

    Filtros opcionais: categoria e intervalo de datas (desde/ate, AAAA-MM-DD, ambos incluídos).
    """
    return _consultar(utilizador, categoria, None, desde, ate)


def procurar_notas(
    utilizador: str,
    texto: str,
    categoria: str | None = None,
    desde: str | None = None,
    ate: str | None = None,
) -> list[dict[str, Any]]:
    """Notas do utilizador que contêm o texto (sem distinguir maiúsculas). Não é procura semântica."""
    if not isinstance(texto, str) or not texto.strip():
        raise ErroFerramenta("Falta o texto a procurar.")
    return _consultar(utilizador, categoria, texto.strip(), desde, ate)
