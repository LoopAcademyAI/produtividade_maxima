"""Acesso por chave e contagem de chamadas para o piloto MCP."""
import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from urllib.request import Request, urlopen


class RedisIndisponivel(RuntimeError):
    pass


def redis(*comando):
    url = os.getenv('UPSTASH_REDIS_REST_URL') or os.getenv('KV_REST_API_URL')
    token = os.getenv('UPSTASH_REDIS_REST_TOKEN') or os.getenv('KV_REST_API_TOKEN')
    if not url or not token or not url.startswith('https://'):
        raise RedisIndisponivel('Redis não configurado')
    try:
        req = Request(url.rstrip('/'), data=json.dumps(list(comando)).encode(),
                      headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method='POST')
        with urlopen(req, timeout=3) as resposta:
            dados = json.load(resposta)
        if 'error' in dados:
            raise RedisIndisponivel('Erro Redis')
        return dados['result']
    except RedisIndisponivel:
        raise
    except Exception as exc:
        raise RedisIndisponivel('Redis indisponível') from exc


def digest(chave):
    return hashlib.sha256(chave.encode()).hexdigest()


def criar_chave(nome):
    nome = ' '.join(nome.split())
    if not nome or len(nome) > 80:
        raise ValueError('Nome inválido')
    chave = secrets.token_urlsafe(16)
    # A substituição é atómica e invalida a chave anterior com o mesmo nome.
    script = """local old=redis.call('HGET',KEYS[2],ARGV[1]); if old then redis.call('HDEL',KEYS[1],old) end; redis.call('HSET',KEYS[1],ARGV[2],ARGV[1]); redis.call('HSET',KEYS[2],ARGV[1],ARGV[2]); return 1"""
    redis('EVAL', script, 2, 'entrelinhas:chaves', 'entrelinhas:nomes', nome, digest(chave))
    return chave


def verificar_chave(chave):
    if not isinstance(chave, str) or not chave or len(chave) > 256:
        return None
    return redis('HGET', 'entrelinhas:chaves', digest(chave))


def revogar(nome):
    nome = ' '.join(nome.split())
    script = """local old=redis.call('HGET',KEYS[2],ARGV[1]); if not old then return 0 end; redis.call('HDEL',KEYS[1],old); redis.call('HDEL',KEYS[2],ARGV[1]); return 1"""
    return bool(redis('EVAL', script, 2, 'entrelinhas:chaves', 'entrelinhas:nomes', nome))


def registar_chamada(nome, categoria, ms):
    if not isinstance(nome, str) or not nome or not isinstance(categoria, str) or not categoria or not isinstance(ms, int) or ms < 0:
        raise ValueError('Evento inválido')
    evento = json.dumps({'nome': nome, 'hora': datetime.now(timezone.utc).isoformat(),
                         'categoria': categoria, 'ms': ms}, ensure_ascii=False)
    redis('EVAL', "redis.call('LPUSH',KEYS[1],ARGV[1]); redis.call('LTRIM',KEYS[1],0,999); return 1", 1, 'entrelinhas:chamadas', evento)


def listar_chamadas():
    return [json.loads(item) for item in redis('LRANGE', 'entrelinhas:chamadas', 0, 999)]
