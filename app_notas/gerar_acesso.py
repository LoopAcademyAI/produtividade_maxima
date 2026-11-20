"""Plano B: gera o URL de uma pessoa; saída contém uma credencial pessoal."""
import argparse
import os
from dotenv import load_dotenv
from acesso import criar_chave

load_dotenv()
parser = argparse.ArgumentParser()
parser.add_argument('nome')
args = parser.parse_args()
base = os.environ.get('MCP_BASE_URL', '').rstrip('/')
if not base.startswith('https://') or '?' in base or '#' in base:
    parser.error('Configura MCP_BASE_URL com HTTPS, sem query ou fragmento')
print(base + '/mcp?key=' + criar_chave(args.nome))
