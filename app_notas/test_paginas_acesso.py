import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import app

class TestPaginas(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'CODIGO_CONVITE': 'teste', 'MCP_BASE_URL': 'https://exemplo.invalid'})
        self.env.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.env.stop()

    @patch('acesso.redis', return_value=1)
    def test_codigo_errado_recusado(self, redis):
        with patch('acesso.criar_chave') as criar:
            r = self.client.post('/api/acesso', json={'nome':'Ana','codigo':'errado'})
            self.assertEqual(r.status_code, 403)
            criar.assert_not_called()

    @patch('acesso.redis', return_value=1)
    @patch('acesso.criar_chave', return_value='chave_teste')
    def test_criar_e_consultar(self, criar, redis):
        r = self.client.post('/api/acesso', json={'nome':'Ana','codigo':'teste'})
        self.assertEqual(r.json()['url'], 'https://exemplo.invalid/mcp?key=chave_teste')
        self.assertEqual(r.headers['cache-control'], 'no-store')
        with patch('acesso.listar_chamadas', return_value=[{'nome':'Ana','categoria':'tarefa','ms':1,'hora':'agora'}]):
            r = self.client.post('/api/uso', json={'codigo':'teste'})
            self.assertEqual(r.json()['eventos'][0]['nome'], 'Ana')
        self.assertEqual(self.client.get('/ligar').status_code, 200)
        self.assertEqual(self.client.get('/uso').status_code, 200)

    @patch('acesso.redis', return_value=31)
    def test_limite(self, redis):
        self.assertEqual(self.client.post('/api/uso', json={'codigo':'teste'}).status_code, 429)

if __name__ == '__main__':
    unittest.main()
