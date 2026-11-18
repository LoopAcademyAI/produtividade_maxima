"""O serviço Captura: recebe uma captura, devolve as categorias.

Qualquer cliente usa o mesmo endpoint: a página web, o marcador (eval/score.py) e os agentes
(Hermes, Claude, ...) através da skill em skill/captura/SKILL.md.

    uv run uvicorn app:app --reload
"""

import json
import pathlib
import sys
import time

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from captura import classificador
from captura.acesso import Limitador, carregar_chaves, quem_e
from captura.categorias import CATEGORIAS

PAGINA = pathlib.Path(__file__).parent / "static" / "index.html"

app = FastAPI(title="Captura", description="Despeja um pensamento, recebe a categoria.")
limitador = Limitador()


class Captura(BaseModel):
    texto: str = Field(min_length=1, max_length=2000, examples=["lembra-me de comprar pilhas AA"])
    origem: str = Field(default="api", max_length=40, description="Quem chamou: web, hermes, claude, score, ...")


class Classificacao(BaseModel):
    categorias: list[str]
    modelo: str
    tokens_prompt: int
    tokens_resposta: int
    segundos: float


def get_classificar():
    return classificador.classificar


def utilizador(authorization: str = Header(default="")):
    chave = authorization.removeprefix("Bearer ").strip()
    nome = quem_e(chave, carregar_chaves()) if chave else None
    if not nome:
        raise HTTPException(status_code=401, detail="Falta uma chave válida: Authorization: Bearer <chave>")
    return nome


def registar(**campos):
    """Uma linha JSON por pedido, nos logs da plataforma. É daqui que sai o custo por pedido."""
    print(json.dumps({"ts": round(time.time(), 3), **campos}, ensure_ascii=False), file=sys.stdout, flush=True)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def pagina():
    return PAGINA.read_text(encoding="utf-8")


@app.get("/saude")
def saude():
    return {"ok": True}


@app.get("/categorias")
def categorias():
    return {"categorias": CATEGORIAS}


@app.post("/classificar", response_model=Classificacao)
def classificar(captura: Captura, nome: str = Depends(utilizador), classificar=Depends(get_classificar)):
    motivo = limitador.permitir(nome)
    if motivo:
        registar(evento="limite", utilizador=nome, motivo=motivo)
        raise HTTPException(status_code=429, detail=motivo)
    try:
        r = classificar(captura.texto)
    except Exception as erro:  # o modelo falhou: dizemos que falhou, não inventamos uma categoria
        registar(evento="erro", utilizador=nome, origem=captura.origem, erro=type(erro).__name__)
        raise HTTPException(status_code=502, detail="O modelo não respondeu. Tenta outra vez daqui a pouco.")
    registar(evento="classificar", utilizador=nome, origem=captura.origem, modelo=r.modelo,
             tokens_prompt=r.tokens_prompt, tokens_resposta=r.tokens_resposta, segundos=r.segundos,
             n_categorias=len(r.categorias))
    return Classificacao(categorias=sorted(r.categorias), modelo=r.modelo, tokens_prompt=r.tokens_prompt,
                         tokens_resposta=r.tokens_resposta, segundos=r.segundos)
