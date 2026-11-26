"""Nomes e aprovação de categorias pessoais (R2.5)."""

import json
import unicodedata
from pathlib import Path

import db

ROOT = Path(__file__).resolve().parent
BASE = sorted(
    json.loads((ROOT / "classificador_config.json").read_text(encoding="utf-8"))[
        "DEFINICOES"
    ]
)
MAX_NOME = 30


class ErroCategoria(ValueError):
    """Nome inválido ou já utilizado por este utilizador."""


def chave_nome(nome: str) -> str:
    return "".join(
        caracter
        for caracter in unicodedata.normalize("NFKD", nome)
        if not unicodedata.combining(caracter)
    )


def normalizar_nome(valor: str) -> str:
    if not isinstance(valor, str):
        raise ErroCategoria("Indica um nome para a categoria.")
    if any(caracter.isspace() and caracter != " " for caracter in valor):
        raise ErroCategoria("O nome da categoria deve ficar numa única linha.")
    nome = " ".join(unicodedata.normalize("NFKC", valor).split()).casefold()
    if not nome:
        raise ErroCategoria("Indica um nome para a categoria.")
    if len(nome) > MAX_NOME:
        raise ErroCategoria("O nome da categoria não pode ter mais de 30 caracteres.")
    if not (nome[0].isalnum() and nome[-1].isalnum()) or any(
        not (caracter.isalnum() or caracter in " -") for caracter in nome
    ):
        raise ErroCategoria("Usa apenas letras, números, espaços ou hífens no nome.")
    if chave_nome(nome) in {chave_nome(base) for base in BASE}:
        raise ErroCategoria("Essa categoria já existe.")
    return nome


def propor(utilizador: str, nome: str) -> dict[str, str]:
    nome = normalizar_nome(nome)
    identificador = db.propor_categoria(utilizador, nome, chave_nome(nome))
    if identificador is None:
        raise ErroCategoria("Essa categoria já existe ou aguarda aprovação.")
    return {"id": identificador, "tipo": "criar_categoria", "nome": nome}


def opcoes(utilizador: str) -> list[str]:
    return sorted([*BASE, *db.categorias_aprovadas(utilizador)])


def pendentes(utilizador: str) -> list[dict[str, str]]:
    return db.categorias_pendentes(utilizador)


def aprovar(utilizador: str, identificador: str) -> str | None:
    return db.decidir_categoria(utilizador, identificador, aprovar=True)


def rejeitar(utilizador: str, identificador: str) -> str | None:
    return db.decidir_categoria(utilizador, identificador, aprovar=False)
