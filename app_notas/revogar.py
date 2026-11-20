import argparse
from dotenv import load_dotenv
from acesso import revogar

load_dotenv()
parser = argparse.ArgumentParser(description='Revoga o acesso de um nome exato.')
parser.add_argument('nome')
args = parser.parse_args()
print('Acesso revogado.' if revogar(args.nome) else 'Nome não encontrado.')
