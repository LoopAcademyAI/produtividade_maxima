import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import app

HEADERS = {'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-06-18'}
INIT = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'teste', 'version': '1'}}}

class Integracao(unittest.TestCase):
    def test_acesso_chamada_e_revogacao(self):
        validas = {'chave-teste': 'Ana'}
        with patch('acesso.verificar_chave', side_effect=lambda chave: validas.get(chave)), patch('acesso.registar_chamada') as registar, patch('app.classificar_texto', return_value='tarefa'):
            with TestClient(app.app) as cliente:
                self.assertEqual(cliente.post('/mcp', headers=HEADERS, json=INIT).status_code, 401)
                self.assertEqual(cliente.post('/mcp?key=falsa', headers=HEADERS, json=INIT).status_code, 401)
                self.assertEqual(cliente.post('/mcp?key=chave-teste', headers=HEADERS, json=INIT).status_code, 200)
                resposta = cliente.post('/mcp?key=chave-teste', headers=HEADERS, json={'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'classificar_nota','arguments':{'texto':'Comprar pilhas'}}})
                self.assertEqual(resposta.status_code, 200, resposta.text)
                self.assertFalse(resposta.json()['result'].get('isError', False), resposta.text)
                registar.assert_called_once()
                self.assertEqual(registar.call_args.args[:2], ('Ana', 'tarefa'))
                validas.clear()
                self.assertEqual(cliente.post('/mcp?key=chave-teste', headers=HEADERS, json=INIT).status_code, 401)

    def test_redis_indisponivel(self):
        with patch('acesso.verificar_chave', side_effect=app.acesso.RedisIndisponivel('falha')):
            with TestClient(app.app) as cliente:
                self.assertEqual(cliente.post('/mcp?key=x', headers=HEADERS, json=INIT).status_code, 503)

if __name__ == '__main__':
    unittest.main()
