import json
import os
import logging
import base64
import hmac
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request as HttpRequest, HTTPRedirectHandler, build_opener
import sys
import time
import uuid
import hmac
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.datastructures import Headers
from starlette.concurrency import run_in_threadpool
from urllib.parse import parse_qs
from openai import OpenAI, OpenAIError
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field
import acesso

from mcp_server import mcp, mcp_app

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
load_dotenv(ROOT.parent / '.env')
CONFIG = json.loads((ROOT / 'classificador_config.json').read_text(encoding='utf-8'))
CATEGORIES = sorted(CONFIG['DEFINICOES'])
MODEL = 'nvidia/nemotron-3-ultra-550b-a55b'


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # O FastAPI não corre o lifespan de sub-apps montadas; o gestor MCP tem de arrancar aqui.
    async with mcp_app.ciclo_de_vida():
        yield


app = FastAPI(title='Entrelinhas', version='1.0.0', lifespan=lifespan)
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


class Convite(BaseModel):
    codigo: str = Field(min_length=1, max_length=200)
    nome: str = Field(default='', max_length=80)


def validar_convite(dados: Convite, request: Request):
    codigo = os.getenv('CODIGO_CONVITE', '')
    if not codigo:
        raise HTTPException(503, 'Convite não configurado.')
    # Limite global partilhado entre instâncias, sem confiar em cabeçalhos do cliente.
    try:
        tentativas = acesso.redis('EVAL', "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n", 1, 'entrelinhas:convites:limite')
    except acesso.RedisIndisponivel:
        raise HTTPException(503, 'Serviço temporariamente indisponível.')
    if int(tentativas) > 30:
        raise HTTPException(429, 'Demasiadas tentativas; aguarda um minuto.')
    if not hmac.compare_digest(codigo.encode(), dados.codigo.encode()):
        raise HTTPException(403, 'Código inválido.')


@app.get('/ligar', include_in_schema=False)
def pagina_ligar():
    headers = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'}
    caminho = ROOT / 'public' / 'ligar.html'
    return FileResponse(caminho, headers=headers) if caminho.is_file() else RedirectResponse('/ligar.html', status_code=307, headers=headers)


@app.get('/uso', include_in_schema=False)
def pagina_uso():
    headers = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'}
    caminho = ROOT / 'public' / 'uso.html'
    return FileResponse(caminho, headers=headers) if caminho.is_file() else RedirectResponse('/uso.html', status_code=307, headers=headers)


@app.post('/api/acesso')
def gerar_acesso(dados: Convite, request: Request):
    validar_convite(dados, request)
    base = os.getenv('MCP_BASE_URL', '').rstrip('/')
    if not base.startswith('https://') or '?' in base or '#' in base:
        raise HTTPException(503, 'URL MCP não configurado.')
    try:
        chave = acesso.criar_chave(dados.nome)
    except ValueError:
        raise HTTPException(422, 'Nome inválido.')
    except acesso.RedisIndisponivel:
        raise HTTPException(503, 'Serviço temporariamente indisponível.')
    from fastapi.responses import JSONResponse
    return JSONResponse({'url': base + '/mcp?key=' + chave}, headers={'Cache-Control': 'no-store'})


@app.post('/api/uso')
def consultar_uso(dados: Convite, request: Request):
    validar_convite(dados, request)
    try:
        eventos = acesso.listar_chamadas()
    except acesso.RedisIndisponivel:
        raise HTTPException(503, 'Serviço temporariamente indisponível.')
    from fastapi.responses import JSONResponse
    return JSONResponse({'eventos': eventos}, headers={'Cache-Control': 'no-store'})


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


class ErroClassificacao(Exception):
    """Falha prevista da classificação; `status` é o código HTTP equivalente."""

    def __init__(self, status: int, mensagem: str):
        super().__init__(mensagem)
        self.status = status
        self.mensagem = mensagem


def classificar_texto(texto: str, request_id: str, origem: str) -> str:
    """Lógica partilhada pela rota HTTP e pela tool MCP. Devolve uma categoria válida."""
    started = time.perf_counter()
    texto = texto.strip()
    if not texto:
        raise ErroClassificacao(422, 'Escreve uma nota antes de adicionar.')
    key = os.environ.get('NVIDIA_API_KEY')
    if not key:
        log_event(logging.ERROR, 'configuracao_em_falta', request_id=request_id, origem=origem, modelo=MODEL)
        raise ErroClassificacao(503, 'A chave NVIDIA não está configurada no servidor.')
    try:
        cliente = OpenAI(base_url='https://integrate.api.nvidia.com/v1', api_key=key, timeout=30, max_retries=1)
        resposta = cliente.chat.completions.create(model=MODEL, messages=[{'role': 'user', 'content': criar_prompt(texto)}],
                    temperature=0, max_tokens=512, extra_body={'chat_template_kwargs': {'enable_thinking': False}})
    except OpenAIError as exc:
        log_event(logging.ERROR, 'modelo_indisponivel', request_id=request_id, origem=origem, modelo=MODEL,
                  tipo_erro=type(exc).__name__, duracao_ms=round((time.perf_counter()-started)*1000))
        raise ErroClassificacao(502, 'Não foi possível classificar a nota. Tenta novamente.') from exc
    conteudo = (resposta.choices[0].message.content or '').strip(" .,'\"[]\n").lower()
    if conteudo not in CATEGORIES:
        log_event(logging.ERROR, 'categoria_invalida', request_id=request_id, origem=origem, modelo=MODEL,
                  tamanho_resposta=len(conteudo), duracao_ms=round((time.perf_counter()-started)*1000))
        raise ErroClassificacao(502, 'O classificador não devolveu uma categoria válida. Tenta novamente.')
    log_event(logging.INFO, 'classificacao_concluida', request_id=request_id, origem=origem, modelo=MODEL,
              categoria=conteudo, duracao_ms=round((time.perf_counter()-started)*1000))
    return conteudo


@app.post('/api/classificar')
def classificar(nota: Nota, request: Request):
    try:
        return {'categoria': classificar_texto(nota.texto, request.state.request_id, origem='http')}
    except ErroClassificacao as exc:
        raise HTTPException(status_code=exc.status, detail=exc.mensagem) from exc


CHAVE_LOG_MCP = 'entrelinhas:mcp:chamadas'
MAX_ENTRADAS_LOG_MCP = 10000


def registar_chamada_mcp(tester: str, categoria: str, estado: str, request_id: str):
    """Acrescenta a chamada ao stream da Upstash. Falhas só geram um aviso; a tool responde na mesma.

    Guarda apenas tester, categoria, estado e hora: nunca o texto da nota.
    """
    url = os.environ.get('UPSTASH_REDIS_REST_URL', '').strip().rstrip('/')
    token = os.environ.get('UPSTASH_REDIS_REST_TOKEN', '').strip()
    if not (url and token):
        log_event(logging.WARNING, 'upstash_por_configurar', request_id=request_id)
        return
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.upstash.io') or
            parsed.path or parsed.query or parsed.fragment or parsed.username):
        log_event(logging.WARNING, 'upstash_configuracao_invalida', request_id=request_id)
        return
    hora = datetime.now(timezone.utc).isoformat(timespec='seconds')
    # MAXLEN ~ limita o tamanho do stream (o ~ deixa o Redis aparar de forma eficiente).
    comando = ['XADD', CHAVE_LOG_MCP, 'MAXLEN', '~', str(MAX_ENTRADAS_LOG_MCP), '*',
               'tester', tester, 'categoria', categoria, 'estado', estado, 'hora', hora]
    req = HttpRequest(url, data=json.dumps(comando).encode(), method='POST',
                      headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
    try:
        with build_opener(SemRedirecionamentos()).open(req, timeout=1.5) as response:
            resultado = json.loads(response.read() or b'{}')
        if 'error' in resultado:
            log_event(logging.WARNING, 'upstash_envio_falhou', request_id=request_id, tipo_erro='RespostaErro')
    except Exception as exc:
        # Só o tipo da falha, sem URL, token ou dados da chamada.
        log_event(logging.WARNING, 'upstash_envio_falhou', request_id=request_id, tipo_erro=type(exc).__name__)


class Classificacao(BaseModel):
    categoria: str = Field(description=f'Uma de: {", ".join(CATEGORIES)}.')


@mcp.tool(
    title='Classificar nota',
    description=('Classifica uma nota curta em português numa única categoria: '
                 f'{", ".join(CATEGORIES)}. Devolve a categoria dominante.'),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)
def classificar_nota(
    texto: Annotated[str, Field(min_length=1, max_length=4000, description='Texto da nota a classificar.')],
    ctx: Context,
) -> Classificacao:
    # Função síncrona: o SDK corre-a numa thread, por isso a chamada bloqueante à NVIDIA não trava o servidor.
    # tester e request_id foram postos no pedido pelo servidor (ExigirChave e middleware), não pelo cliente.
    estado_pedido = ctx.request_context.request.state
    tester = estado_pedido.tester
    request_id = getattr(estado_pedido, 'request_id', None) or uuid.uuid4().hex
    inicio = time.perf_counter()
    try:
        categoria = classificar_texto(texto, request_id, origem='mcp')
    except ErroClassificacao as exc:
        # ToolError devolve isError=True com esta mensagem ao cliente (sem traceback).
        raise ToolError(exc.mensagem) from exc
    try:
        acesso.registar_chamada(tester, categoria, round((time.perf_counter() - inicio) * 1000))
    except acesso.RedisIndisponivel:
        logger.warning('mcp_registo_indisponivel')
    return Classificacao(categoria=categoria)


TAMANHO_MINIMO_CHAVE = 24


def carregar_testers() -> dict[str, str]:
    """Lê MCP_TESTERS ({"nome": "chave", ...}). Entradas inválidas ou chaves curtas são ignoradas."""
    bruto = os.environ.get('MCP_TESTERS', '').strip()
    if not bruto:
        return {}
    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError:
        logger.warning('mcp_testers_json_invalido')
        return {}
    if not isinstance(dados, dict):
        logger.warning('mcp_testers_json_invalido')
        return {}
    testers = {}
    for nome, chave in dados.items():
        if isinstance(nome, str) and nome.strip() and isinstance(chave, str) and len(chave) >= TAMANHO_MINIMO_CHAVE:
            testers[nome.strip()] = chave
        else:
            # Só o nome, nunca a chave.
            logger.warning('mcp_tester_ignorado nome=%s', nome if isinstance(nome, str) else '?')
    return testers


def identificar_tester(authorization: str | None, testers: dict[str, str]) -> str | None:
    """Devolve o nome do tester dono da chave em `Authorization: Bearer <chave>`, ou None."""
    esquema, _, chave = (authorization or '').strip().partition(' ')
    chave = chave.strip()
    if esquema.lower() != 'bearer' or not chave:
        return None
    encontrado = None
    for nome, esperada in testers.items():
        # compare_digest em todas as entradas: o tempo de resposta não revela quais chaves existem.
        if hmac.compare_digest(chave.encode(), esperada.encode()):
            encontrado = nome
    return encontrado


class ExigirChave:
    """Envolve o sub-app MCP: pedidos a /mcp sem chave válida são rejeitados antes de chegar ao SDK."""

    def __init__(self, destino):
        self.destino = destino

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['path'] != '/mcp':
            # Outros caminhos seguem para o sub-app, que responde 404 como antes.
            return await self.destino(scope, receive, send)
        request_id = scope.get('state', {}).get('request_id') or uuid.uuid4().hex
        authorization = Headers(scope=scope).get('authorization')
        esquema, _, token = (authorization or '').partition(' ')
        query = parse_qs(scope.get('query_string', b'').decode('ascii', errors='replace'))
        chaves = query.get('key', [])
        if len(chaves) > 1:
            resposta = JSONResponse({'erro': 'Chave inválida.'}, status_code=401)
            return await resposta(scope, receive, send)
        chave = chaves[0] if chaves else (token.strip() if esquema.lower() == 'bearer' else '')
        try:
            tester = await run_in_threadpool(acesso.verificar_chave, chave)
        except acesso.RedisIndisponivel:
            resposta = JSONResponse({'erro': 'Serviço de acesso indisponível.'}, status_code=503)
            return await resposta(scope, receive, send)
        if tester is None:
            motivo = 'sem_chave' if not chave else 'chave_invalida'
            log_event(logging.WARNING, 'mcp_acesso_negado', request_id=request_id, motivo=motivo)
            resposta = JSONResponse({'erro': 'Chave em falta ou inválida. Usa Authorization: Bearer <chave>.'},
                                    status_code=401, headers={'WWW-Authenticate': 'Bearer'})
            return await resposta(scope, receive, send)
        # Guardado pelo servidor depois de validar a chave; a tool lê-o via ctx (passo 4).
        scope = {**scope, 'state': {**scope.get('state', {}), 'tester': tester}}
        await self.destino(scope, receive, send)


# Montado no fim: um Mount em '/' apanha todos os caminhos, por isso tem de vir depois
# das rotas acima. O sub-app só responde em /mcp; o resto dá 404 como antes.
app.mount('/', ExigirChave(mcp_app))
