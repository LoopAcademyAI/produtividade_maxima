import json
import os
import logging
import base64
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request as HttpRequest, HTTPRedirectHandler, build_opener
import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field

import db

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
load_dotenv(ROOT.parent / '.env')
CONFIG = json.loads((ROOT / 'classificador_config.json').read_text(encoding='utf-8'))
CATEGORIES = sorted(CONFIG['DEFINICOES'])
MODEL = 'nvidia/nemotron-3-ultra-550b-a55b'
app = FastAPI(title='Entrelinhas', version='1.0.0')
logger = logging.getLogger('entrelinhas')
logger.setLevel(logging.INFO)
if not logger.handlers:
    info_handler = logging.StreamHandler(sys.stdout)
    info_handler.setLevel(logging.INFO)
    info_handler.addFilter(lambda record: record.levelno < logging.ERROR)
    error_handler = logging.StreamHandler(sys.stderr)
    error_handler.setLevel(logging.ERROR)
    for handler in (info_handler, error_handler):
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)
logger.propagate = False


class SemRedirecionamentos(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def enviar_loki(registo: dict, level: int):
    """Envia só os eventos seguros da aplicação; falhas não afetam os pedidos."""
    url = os.environ.get('LOKI_PUSH_URL', '').strip()
    user = os.environ.get('LOKI_USER', '').strip()
    token = os.environ.get('LOKI_TOKEN', '').strip()
    if not (url and user and token):
        return
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or not parsed.hostname or
            not parsed.hostname.endswith('.grafana.net') or
            parsed.path.rstrip('/') != '/loki/api/v1/push' or parsed.query or parsed.fragment or parsed.username):
        logger.warning('grafana_configuracao_invalida')
        return
    record = {**registo, 'nivel': logging.getLevelName(level).lower(),
              'timestamp': datetime.now(timezone.utc).isoformat()}
    payload = {'streams': [{'stream': {'service_name': 'entrelinhas', 'environment': 'production'},
                           'values': [[str(time.time_ns()), json.dumps(record, ensure_ascii=False)]]}]}
    auth = base64.b64encode(f'{user}:{token}'.encode()).decode()
    req = HttpRequest(url, data=json.dumps(payload).encode(), method='POST',
                      headers={'Content-Type': 'application/json', 'Authorization': 'Basic ' + auth})
    try:
        with build_opener(SemRedirecionamentos()).open(req, timeout=1.5) as response:
            response.read()
    except Exception as exc:
        # Só o tipo da falha, sem URL, credenciais, conteúdo HTTP ou dados privados.
        logger.warning('grafana_envio_falhou tipo_erro=%s', type(exc).__name__)


def log_event(level: int, event: str, **fields):
    # Não registar o texto da nota, o prompt, as chaves nem respostas livres.
    registo = {'event': event, **fields}
    logger.log(level, json.dumps(registo, ensure_ascii=False))
    enviar_loki(registo, level)


@app.middleware('http')
async def observar_pedido(request: Request, call_next):
    request_id = uuid.uuid4().hex
    request.state.request_id = request_id
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        log_event(logging.ERROR, 'pedido_erro_inesperado', request_id=request_id,
                  rota=request.url.path, metodo=request.method, tipo_erro=type(exc).__name__,
                  duracao_ms=round((time.perf_counter()-start)*1000))
        raise
    response.headers['X-Request-ID'] = request_id
    log_event(logging.INFO, 'pedido_concluido', request_id=request_id, rota=request.url.path,
              metodo=request.method, status=response.status_code,
              duracao_ms=round((time.perf_counter()-start)*1000))
    return response


class Nota(BaseModel):
    texto: str = Field(min_length=1, max_length=4000)


def criar_prompt(texto: str) -> str:
    definicoes = '\n'.join(f'- {c}: {CONFIG["DEFINICOES"][c]}' for c in CATEGORIES)
    exemplos = '\n'.join(f'Captura: {CONFIG["EXAMPLES"][c]}\nCategorias: {c}' for c in CATEGORIES)
    return (f"Categorias possíveis: {', '.join(CATEGORIES)}.\n"
            f"{CONFIG['PROMPTS']['P2_dominante']}\n\n"
            f'Definições:\n{definicoes}\n\nExemplos:\n{exemplos}\n\nCaptura: {texto}')


@app.get('/', include_in_schema=False)
def pagina():
    return FileResponse(ROOT / 'public' / 'index.html')


@app.get('/api/health')
def health():
    return {'status': 'ok'}


def classificar_texto(texto: str, request_id: str) -> str:
    """Devolve a categoria da nota, ou levanta HTTPException. Usado por /api/classificar e por /api/notas."""
    started = time.perf_counter()
    # Experiência temporária: categoria fora da lista, sem tratamento de erro.
    if texto == "TESTE OBSERVABILIDADE E":
        resposta = "E"
        return CATEGORIES[CATEGORIES.index(resposta)]
    if not texto:
        raise HTTPException(status_code=422, detail='Escreve uma nota antes de adicionar.')
    key = os.environ.get('NVIDIA_API_KEY')
    if not key:
        log_event(logging.ERROR, 'configuracao_em_falta', request_id=request_id, modelo=MODEL)
        raise HTTPException(status_code=503, detail='A chave NVIDIA não está configurada no servidor.')
    try:
        cliente = OpenAI(base_url='https://integrate.api.nvidia.com/v1', api_key=key, timeout=30, max_retries=1)
        resposta = cliente.chat.completions.create(model=MODEL, messages=[{'role': 'user', 'content': criar_prompt(texto)}],
                    temperature=0, max_tokens=512, extra_body={'chat_template_kwargs': {'enable_thinking': False}})
    except OpenAIError as exc:
        log_event(logging.ERROR, 'modelo_indisponivel', request_id=request_id, modelo=MODEL,
                  tipo_erro=type(exc).__name__, duracao_ms=round((time.perf_counter()-started)*1000))
        raise HTTPException(status_code=502, detail='Não foi possível classificar a nota. Tenta novamente.') from exc
    conteudo = (resposta.choices[0].message.content or '').strip(" .,'\"[]\n").lower()
    if conteudo not in CATEGORIES:
        log_event(logging.ERROR, 'categoria_invalida', request_id=request_id, modelo=MODEL,
                  tamanho_resposta=len(conteudo), duracao_ms=round((time.perf_counter()-started)*1000))
        raise HTTPException(status_code=502, detail='O classificador não devolveu uma categoria válida. Tenta novamente.')
    log_event(logging.INFO, 'classificacao_concluida', request_id=request_id, modelo=MODEL,
              categoria=conteudo, duracao_ms=round((time.perf_counter()-started)*1000))
    return conteudo


@app.post('/api/classificar')
def classificar(nota: Nota, request: Request):
    return {'categoria': classificar_texto(nota.texto.strip(), request.state.request_id)}


# --- Notas guardadas no servidor (R1). Porquê e limites: BASE_DE_DADOS.md ---

def validar_utilizador(x_utilizador: str | None) -> str:
    """Ainda não há contas: o navegador gera um identificador e manda-o em cada pedido.
    Isto separa as notas de cada pessoa, mas NÃO é autenticação (quem souber o id lê as notas). Ticket próprio."""
    try:
        return str(uuid.UUID(x_utilizador or ''))
    except ValueError:
        raise HTTPException(status_code=400, detail='Falta o cabeçalho X-Utilizador (um UUID).')


class NotaImportada(BaseModel):
    texto: str = Field(min_length=1, max_length=4000)
    categoria: str
    criada: str | None = None
    id: str | None = None


@app.post('/api/notas', status_code=201)
def criar_nota(nota: Nota, request: Request, x_utilizador: str | None = Header(default=None)):
    utilizador = validar_utilizador(x_utilizador)
    texto = nota.texto.strip()
    categoria = classificar_texto(texto, request.state.request_id)
    guardada = db.criar(utilizador, texto, categoria)
    log_event(logging.INFO, 'nota_guardada', request_id=request.state.request_id, categoria=categoria)
    return guardada


@app.get('/api/notas')
def listar_notas(categoria: str | None = None, q: str | None = None, x_utilizador: str | None = Header(default=None)):
    if categoria and categoria not in CATEGORIES:
        raise HTTPException(status_code=422, detail=f'Categoria desconhecida. Possíveis: {", ".join(CATEGORIES)}.')
    return db.listar(validar_utilizador(x_utilizador), categoria=categoria, procura=q)


@app.delete('/api/notas/{id}', status_code=204)
def apagar_nota(id: str, x_utilizador: str | None = Header(default=None)):
    if not db.apagar(validar_utilizador(x_utilizador), id):
        raise HTTPException(status_code=404, detail='Nota não encontrada.')


@app.post('/api/notas/importar')
def importar_notas(notas: list[NotaImportada], x_utilizador: str | None = Header(default=None)):
    """Uma vez por navegador: passa as notas do localStorage para o servidor, sem as reclassificar."""
    utilizador = validar_utilizador(x_utilizador)
    existentes = {n['id'] for n in db.listar(utilizador, limite=10_000)}
    novas = [n for n in notas if n.categoria in CATEGORIES and n.id not in existentes]
    for n in novas:
        db.criar(utilizador, n.texto, n.categoria, criada_em=n.criada, id=n.id)
    return {'importadas': len(novas), 'ignoradas': len(notas) - len(novas)}
