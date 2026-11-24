"""Grafo LangGraph para o esqueleto do agente Entrelinhas."""

import json
import operator
from typing import Annotated, Any, Callable, TypedDict

from langchain_core.runnables import RunnableLambda
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
)

MAX_PASSOS_AGENTE = 6
RESPOSTA_LIMITE = (
    "O agente atingiu o limite de 6 passos sem concluir o pedido. "
    "Tenta reformular ou dividir o pedido em partes mais pequenas."
)
RESPOSTA_FERRAMENTA_INDISPONIVEL = (
    "Esta ferramenta ainda não está disponível. Não foi executada nenhuma ação."
)


class ChamadaFerramenta(TypedDict):
    id: str
    nome: str
    args: dict[str, Any]


class RespostaModelo(TypedDict):
    texto: str
    chamadas: list[ChamadaFerramenta]


class EstadoAgente(TypedDict):
    utilizador: str
    conversa: str
    mensagens: Annotated[list[ChatCompletionMessageParam], operator.add]
    ferramentas: Annotated[list[dict[str, Any]], operator.add]
    chamadas_pendentes: list[ChamadaFerramenta]
    passos: int
    resposta: str


class AtualizacaoEstadoAgente(TypedDict, total=False):
    mensagens: list[ChatCompletionMessageParam]
    ferramentas: list[dict[str, Any]]
    chamadas_pendentes: list[ChamadaFerramenta]
    passos: int
    resposta: str


ModeloAgente = Callable[[list[ChatCompletionMessageParam]], RespostaModelo]


def executar_agente(
    mensagem: str,
    utilizador: str,
    conversa: str,
    chamar_modelo: ModeloAgente,
) -> dict[str, Any]:
    """Executa o grafo sem persistir estado entre pedidos."""

    def chamar_modelo_no(estado: EstadoAgente) -> AtualizacaoEstadoAgente:
        resultado = chamar_modelo(estado["mensagens"])
        chamadas = resultado["chamadas"]
        mensagem_assistente: ChatCompletionAssistantMessageParam = {
            "role": "assistant",
            "content": resultado["texto"],
        }
        if chamadas:
            mensagem_assistente["tool_calls"] = [
                {
                    "id": chamada["id"],
                    "type": "function",
                    "function": {
                        "name": chamada["nome"],
                        "arguments": json.dumps(chamada["args"], ensure_ascii=False),
                    },
                }
                for chamada in chamadas
            ]
        return {
            "mensagens": [mensagem_assistente],
            "ferramentas": [
                {"nome": chamada["nome"], "args": chamada["args"]}
                for chamada in chamadas
            ],
            "chamadas_pendentes": chamadas,
            "passos": estado["passos"] + 1,
            "resposta": resultado["texto"],
        }

    def executar_ferramentas_no(estado: EstadoAgente) -> AtualizacaoEstadoAgente:
        return {
            "mensagens": [
                {
                    "role": "tool",
                    "tool_call_id": chamada["id"],
                    "content": RESPOSTA_FERRAMENTA_INDISPONIVEL,
                }
                for chamada in estado["chamadas_pendentes"]
            ],
            "chamadas_pendentes": [],
        }

    def decidir_proximo_passo(estado: EstadoAgente) -> str:
        if not estado["chamadas_pendentes"]:
            return "terminar"
        if estado["passos"] >= MAX_PASSOS_AGENTE:
            return "limite"
        return "ferramentas"

    def terminar_por_limite(estado: EstadoAgente) -> AtualizacaoEstadoAgente:
        return {"resposta": RESPOSTA_LIMITE, "passos": estado["passos"]}

    grafo = StateGraph(EstadoAgente)
    grafo.add_node("modelo", RunnableLambda(chamar_modelo_no))
    grafo.add_node("ferramentas", RunnableLambda(executar_ferramentas_no))
    grafo.add_node("limite", RunnableLambda(terminar_por_limite))
    grafo.add_edge(START, "modelo")
    grafo.add_conditional_edges(
        "modelo",
        decidir_proximo_passo,
        {"terminar": END, "ferramentas": "ferramentas", "limite": "limite"},
    )
    grafo.add_edge("ferramentas", "modelo")
    grafo.add_edge("limite", END)

    aplicacao = grafo.compile()
    estado_inicial: EstadoAgente = {
        "utilizador": utilizador,
        "conversa": conversa,
        "mensagens": [
            {
                "role": "system",
                "content": "Responde em português. Usa ferramentas apenas quando necessário.",
            },
            {"role": "user", "content": mensagem},
        ],
        "ferramentas": [],
        "chamadas_pendentes": [],
        "passos": 0,
        "resposta": "",
    }

    try:
        estado_final = aplicacao.invoke(
            estado_inicial,
            config={"recursion_limit": MAX_PASSOS_AGENTE * 2 + 2},
        )
    except GraphRecursionError:
        estado_final = {
            **estado_inicial,
            "resposta": RESPOSTA_LIMITE,
        }

    return {
        "resposta": estado_final["resposta"],
        "conversa": conversa,
        "ferramentas": estado_final["ferramentas"],
        "pendente": None,
    }
