"""Grafo LangGraph para o esqueleto do agente Entrelinhas."""

import json
import operator
from typing import Annotated, Any, Callable, TypedDict

from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
)

MAX_PASSOS_AGENTE = 6
MAX_HISTORICO_MENSAGENS = 20
RESPOSTA_LIMITE = (
    "O agente atingiu o limite de 6 passos sem concluir o pedido. "
    "Tenta reformular ou dividir o pedido em partes mais pequenas."
)
RESPOSTA_FERRAMENTA_INDISPONIVEL = (
    "Esta ferramenta ainda não está disponível. Não foi executada nenhuma ação."
)
RESPOSTA_LIMITE_FERRAMENTA = (
    "O limite de passos do agente foi atingido; esta ferramenta não foi executada."
)


class ChamadaFerramenta(TypedDict):
    id: str
    nome: str
    args: dict[str, Any]


class RespostaModelo(TypedDict):
    texto: str
    chamadas: list[ChamadaFerramenta]


class EstadoAgente(TypedDict, total=False):
    mensagem_atual: str
    mensagens: Annotated[list[ChatCompletionMessageParam], operator.add]
    ferramentas: list[dict[str, Any]]
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


def limitar_historico(
    mensagens: list[ChatCompletionMessageParam],
) -> list[ChatCompletionMessageParam]:
    sistema = [m for m in mensagens if m.get("role") == "system"]
    historico = [m for m in mensagens if m.get("role") != "system"]
    historico = historico[-MAX_HISTORICO_MENSAGENS:]
    while historico and historico[0].get("role") == "tool":
        historico.pop(0)
    return [*sistema, *historico]


def executar_agente(
    mensagem: str,
    conversa: str,
    thread_id: str,
    chamar_modelo: ModeloAgente,
    checkpointer: BaseCheckpointSaver,
) -> dict[str, Any]:
    """Executa ou retoma o grafo persistido para esta conversa."""

    def preparar_turno_no(estado: EstadoAgente) -> AtualizacaoEstadoAgente:
        mensagens = estado.get("mensagens", [])
        novas_mensagens: list[ChatCompletionMessageParam] = []
        if not any(m.get("role") == "system" for m in mensagens):
            novas_mensagens.append(
                {
                    "role": "system",
                    "content": "Responde em português. Usa ferramentas apenas quando necessário.",
                }
            )
        novas_mensagens.append({"role": "user", "content": estado["mensagem_atual"]})
        return {
            "mensagens": novas_mensagens,
            "ferramentas": [],
            "chamadas_pendentes": [],
            "passos": 0,
            "resposta": "",
        }

    def chamar_modelo_no(estado: EstadoAgente) -> AtualizacaoEstadoAgente:
        resultado = chamar_modelo(limitar_historico(estado.get("mensagens", [])))
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
            "ferramentas": estado.get("ferramentas", [])
            + [
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
        return {
            "mensagens": [
                {
                    "role": "tool",
                    "tool_call_id": chamada["id"],
                    "content": RESPOSTA_LIMITE_FERRAMENTA,
                }
                for chamada in estado["chamadas_pendentes"]
            ],
            "chamadas_pendentes": [],
            "resposta": RESPOSTA_LIMITE,
            "passos": estado["passos"],
        }

    grafo = StateGraph(EstadoAgente)
    grafo.add_node("preparar_turno", RunnableLambda(preparar_turno_no))
    grafo.add_node("modelo", RunnableLambda(chamar_modelo_no))
    grafo.add_node("ferramentas", RunnableLambda(executar_ferramentas_no))
    grafo.add_node("limite", RunnableLambda(terminar_por_limite))
    grafo.add_edge(START, "preparar_turno")
    grafo.add_edge("preparar_turno", "modelo")
    grafo.add_conditional_edges(
        "modelo",
        decidir_proximo_passo,
        {"terminar": END, "ferramentas": "ferramentas", "limite": "limite"},
    )
    grafo.add_edge("ferramentas", "modelo")
    grafo.add_edge("limite", END)

    aplicacao = grafo.compile(checkpointer=checkpointer)

    try:
        estado_final = aplicacao.invoke(
            {"mensagem_atual": mensagem},
            config={
                "configurable": {"thread_id": thread_id},
                "recursion_limit": MAX_PASSOS_AGENTE * 2 + 2,
            },
        )
    except GraphRecursionError:
        return {
            "resposta": RESPOSTA_LIMITE,
            "conversa": conversa,
            "ferramentas": [],
            "pendente": None,
        }

    return {
        "resposta": estado_final.get("resposta", ""),
        "conversa": conversa,
        "ferramentas": estado_final.get("ferramentas", []),
        "pendente": None,
    }
