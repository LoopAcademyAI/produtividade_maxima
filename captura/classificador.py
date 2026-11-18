"""O classificador: texto → conjunto de categorias. É aqui que entra a vossa decisão de quinta.

Começa com o zero-shot do spike de quarta (funciona, mas é fraco). A assinatura não muda:
classificar(texto) -> Resultado, para o serviço, o marcador e os agentes continuarem a funcionar.
"""

import os
import time
from dataclasses import dataclass, field

from openai import OpenAI

from captura.categorias import CATEGORIAS, DEFINICOES

MODELO = os.environ.get("CAPTURA_MODELO", "nvidia/nemotron-3.5-bolt-e4b")
BASE_URL = os.environ.get("CAPTURA_BASE_URL", "https://integrate.api.nvidia.com/v1")


@dataclass
class Resultado:
    categorias: set[str]
    modelo: str
    tokens_prompt: int = 0
    tokens_resposta: int = 0
    segundos: float = 0.0
    resposta_bruta: str = field(default="", repr=False)


_client = None


def _cliente():
    global _client
    if _client is None:
        _client = OpenAI(base_url=BASE_URL, api_key=os.environ["NVIDIA_API_KEY"])
    return _client


def prompt_para(texto):
    definicoes = "".join(f"- {c}: {d}\n" for c, d in DEFINICOES.items())
    return (
        f"Categorias possíveis: {', '.join(CATEGORIAS)}.\n"
        + (f"O que quer dizer cada uma:\n{definicoes}" if definicoes else "")
        + "Classifica a captura numa ou mais categorias. Responde só com as categorias, separadas por vírgulas.\n\n"
        + f"Captura: {texto}"
    )


def interpretar(resposta):
    """Aceita só categorias da nossa lista. O resto é ignorado (e conta como erro no marcador)."""
    palavras = {p.strip(" .,'\"[]*").lower() for p in resposta.replace("\n", ",").split(",")}
    return {p for p in palavras if p in CATEGORIAS}


def classificar(texto):
    inicio = time.time()
    r = _cliente().chat.completions.create(
        model=MODELO,
        messages=[{"role": "user", "content": prompt_para(texto)}],
        temperature=0,
        max_tokens=60,
    )
    resposta = r.choices[0].message.content or ""
    return Resultado(
        categorias=interpretar(resposta),
        modelo=MODELO,
        tokens_prompt=r.usage.prompt_tokens if r.usage else 0,
        tokens_resposta=r.usage.completion_tokens if r.usage else 0,
        segundos=round(time.time() - inicio, 2),
        resposta_bruta=resposta,
    )
