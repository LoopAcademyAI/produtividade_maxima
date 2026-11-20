import json
import unittest
from unittest.mock import patch
import acesso


class TestAcesso(unittest.TestCase):
    def test_verificacao_nao_envia_chave_em_claro(self):
        with patch('acesso.redis', return_value='Ana') as redis:
            self.assertEqual(acesso.verificar_chave('segredo'), 'Ana')
            self.assertNotIn('segredo', redis.call_args.args)
        self.assertIsNone(acesso.verificar_chave(''))

    def test_criacao_e_revogacao(self):
        with patch('acesso.redis', return_value=1) as redis:
            chave = acesso.criar_chave(' Ana ')
            self.assertGreaterEqual(len(chave), 20)
            self.assertNotIn(chave, redis.call_args.args)
            self.assertTrue(acesso.revogar('Ana'))
        with self.assertRaises(ValueError):
            acesso.criar_chave(' ')

    def test_evento_sem_nota(self):
        with patch('acesso.redis', return_value=1) as redis:
            acesso.registar_chamada('Ana', 'tarefa', 12)
            evento = json.loads(redis.call_args.args[-1])
            self.assertEqual(set(evento), {'nome', 'hora', 'categoria', 'ms'})
            self.assertEqual(evento['categoria'], 'tarefa')


if __name__ == '__main__':
    unittest.main()
