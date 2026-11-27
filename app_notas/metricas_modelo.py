"""Mede chamadas ao fornecedor sem guardar conteúdo da conversa ou da nota."""

import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

Resultado = TypeVar("Resultado")


def _tokens(usage: Any, campo: str) -> int | None:
    valor = getattr(usage, campo, None)
    return valor if type(valor) is int and valor >= 0 else None


def medir_chamada_modelo(
    chamar: Callable[[], Resultado],
    *,
    modelo: str,
    etapa: str,
    origem: str,
    request_id: str | None = None,
    registar: Callable[..., None] | None = None,
) -> Resultado:
    """Regista uma linha por chamada SDK; tentativas internas contam na latência."""
    inicio = time.perf_counter()
    try:
        resposta = chamar()
    except Exception as exc:
        if registar is not None:
            registar(
                logging.ERROR,
                "chamada_modelo",
                request_id=request_id,
                modelo=modelo,
                etapa=etapa,
                origem=origem,
                estado="erro",
                tipo_erro=type(exc).__name__,
                duracao_ms=round((time.perf_counter() - inicio) * 1000, 2),
            )
        raise

    duracao_ms = round((time.perf_counter() - inicio) * 1000, 2)
    if registar is not None:
        usage = getattr(resposta, "usage", None)
        entrada = _tokens(usage, "prompt_tokens")
        saida = _tokens(usage, "completion_tokens")
        campos: dict[str, Any] = {
            "request_id": request_id,
            "modelo": modelo,
            "etapa": etapa,
            "origem": origem,
            "estado": "ok",
            "duracao_ms": duracao_ms,
        }
        if entrada is not None:
            campos["tokens_entrada"] = entrada
        if saida is not None:
            campos["tokens_saida"] = saida
        registar(logging.INFO, "chamada_modelo", **campos)
    return resposta
