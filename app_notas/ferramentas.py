"""Ferramentas de leitura de notas para o agente (R2.4).

Recebem sempre o utilizador do pedido (X-Utilizador), nunca do modelo: o filtro por
utilizador é feito na própria consulta SQL, por isso nenhuma ferramenta vê notas de outra pessoa.
"""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

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


def propor_alteracoes_categoria(
    utilizador: str, propostas: list[dict[str, Any]]
) -> dict[str, Any]:
    """Persiste propostas válidas sem alterar as notas."""
    guardadas = db.criar_propostas_categoria(
        _validar_utilizador(utilizador), propostas, CATEGORIAS
    )
    return {
        "lote_id": guardadas[0]["lote_id"] if guardadas else None,
        "total": len(guardadas),
        "propostas": guardadas,
    }


# --- Ligação ao agente (R2.4b) ---

_FILTROS = {
    "categoria": {
        "type": "string",
        "enum": CATEGORIAS,
        "description": "Só notas desta categoria. 'tarefa' são coisas para fazer.",
    },
    "desde": {
        "type": "string",
        "description": "Primeiro dia incluído, AAAA-MM-DD (data de criação da nota, UTC).",
    },
    "ate": {
        "type": "string",
        "description": "Último dia incluído, AAAA-MM-DD (data de criação da nota, UTC).",
    },
}

ESQUEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "listar_notas",
            "description": (
                "Lista as notas do utilizador, das mais recentes para as mais antigas. "
                "Usa para perguntas como 'o que tenho para fazer?' (categoria 'tarefa')."
            ),
            "parameters": {
                "type": "object",
                "properties": _FILTROS,
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "procurar_notas",
            "description": (
                "Procura notas do utilizador que contêm um texto exato, como um nome "
                "ou uma palavra. Usa para perguntas como 'tenho alguma coisa com a Sofia?'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "texto": {
                        "type": "string",
                        "description": "Palavra ou nome a procurar, por exemplo 'Sofia'.",
                    },
                    **_FILTROS,
                },
                "required": ["texto"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propor_alteracoes_categoria",
            "description": (
                "Cria propostas pendentes para alterar categorias das notas do utilizador. "
                "Usa apenas depois de listar as notas e quando a pessoa pedir para as "
                "reorganizar. Só guarda propostas; nunca altera categorias. Propõe apenas "
                "categorias válidas diferentes da atual. A pessoa terá de aprovar cada uma."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "propostas": {
                        "type": "array",
                        "maxItems": 50,
                        "items": {
                            "type": "object",
                            "properties": {
                                "nota_id": {
                                    "type": "string",
                                    "description": "ID de uma nota devolvida por listar_notas.",
                                },
                                "categoria": {
                                    "type": "string",
                                    "enum": CATEGORIAS,
                                    "description": "Categoria sugerida para a nota.",
                                },
                            },
                            "required": ["nota_id", "categoria"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["propostas"],
                "additionalProperties": False,
            },
        },
    },
]

_FUNCOES: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "listar_notas": listar_notas,
    "procurar_notas": procurar_notas,
}
_ARGUMENTOS = {
    nome: set(esquema["function"]["parameters"]["properties"])
    for nome, esquema in zip(_FUNCOES, ESQUEMAS)
}


def executar(nome: str, utilizador: str, args: dict[str, Any]) -> str:
    """Executa uma ferramenta pedida pelo modelo e devolve o texto da mensagem 'tool'.

    O utilizador vem do pedido; argumentos fora do esquema (por exemplo 'utilizador')
    são recusados. Os erros voltam ao modelo como texto, para ele poder corrigir o pedido.
    """
    if nome == "propor_alteracoes_categoria":
        extra = set(args) - {"propostas"}
        if extra or set(args) != {"propostas"}:
            return "Erro: argumentos inválidos para propor alterações de categoria."
        try:
            resultado = propor_alteracoes_categoria(utilizador, args["propostas"])
        except (ErroFerramenta, TypeError) as exc:
            return f"Erro: {exc}"
        return json.dumps(resultado, ensure_ascii=False)
    if nome not in _FUNCOES:
        return (
            f"Erro: a ferramenta {nome} não existe. Disponíveis: {', '.join(_FUNCOES)}."
        )
    extra = set(args) - _ARGUMENTOS[nome]
    if extra:
        return f"Erro: argumentos não aceites: {', '.join(sorted(extra))}."
    try:
        notas = _FUNCOES[nome](utilizador, **args)
    except (ErroFerramenta, TypeError) as exc:
        return f"Erro: {exc}"
    return json.dumps({"total": len(notas), "notas": notas}, ensure_ascii=False)
