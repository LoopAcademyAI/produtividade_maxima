"""Quem pode usar o serviço, e quanto.

As chaves vêm da variável de ambiente CAPTURA_KEYS ("nome:chave,nome:chave"), guardada como segredo
na plataforma de deploy. Nunca no repositório, nunca na página.

O limite de pedidos vive na memória do processo. Chega para um MVP com um só processo; com vários
processos (ou serverless a escalar) cada um tem o seu contador. Isso é uma limitação conhecida.
"""

import os
import secrets
import time
from collections import defaultdict, deque

POR_MINUTO = int(os.environ.get("CAPTURA_LIMITE_MINUTO", "20"))
POR_DIA = int(os.environ.get("CAPTURA_LIMITE_DIA", "300"))


def carregar_chaves(valor=None):
    valor = os.environ.get("CAPTURA_KEYS", "") if valor is None else valor
    chaves = {}
    for par in valor.split(","):
        if ":" in par:
            nome, chave = par.split(":", 1)
            if nome.strip() and chave.strip():
                chaves[chave.strip()] = nome.strip()
    return chaves


def quem_e(chave, chaves):
    for conhecida, nome in chaves.items():
        if secrets.compare_digest(conhecida, chave):
            return nome
    return None


class Limitador:
    def __init__(self, por_minuto=POR_MINUTO, por_dia=POR_DIA, relogio=time.time):
        self.por_minuto, self.por_dia, self.relogio = por_minuto, por_dia, relogio
        self.pedidos = defaultdict(deque)

    def permitir(self, nome):
        """Devolve None se pode avançar, ou a razão pela qual não pode."""
        agora = self.relogio()
        fila = self.pedidos[nome]
        while fila and agora - fila[0] > 86400:
            fila.popleft()
        if len(fila) >= self.por_dia:
            return f"limite diário atingido ({self.por_dia} pedidos)"
        if sum(1 for t in fila if agora - t < 60) >= self.por_minuto:
            return f"limite por minuto atingido ({self.por_minuto} pedidos)"
        fila.append(agora)
        return None
