"""Testes offline da avaliação de acordo R4.2."""

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import app
import avaliar_acordo
from avaliar_acordo import (
    NUM_VOTOS,
    TEMPERATURA,
    apurar,
    carregar_estado,
    classificar_amostra,
    digest_golden,
    novo_estado,
    recolher_votos,
    relatorio,
)


class TestarAcordo(unittest.TestCase):
    def setUp(self) -> None:
        self.certa, self.errada, self.terceira = app.CATEGORIES[:3]
        self.notas = [{"texto": "texto privado da nota", "categoria": self.certa}]

    def test_apurar_consenso_errado_e_acerto_parcial(self) -> None:
        self.assertEqual(
            apurar([self.errada] * NUM_VOTOS, self.certa), (self.errada, 5, False)
        )
        self.assertEqual(
            apurar([self.certa] * 3 + [self.errada] * 2, self.certa),
            (self.certa, 3, True),
        )

    def test_empate_nao_escolhe_categoria(self) -> None:
        self.assertEqual(
            apurar([self.certa] * 2 + [self.errada] * 2 + [self.terceira], self.certa),
            (None, 2, False),
        )

    def test_relatorio_mostra_acordo_e_erro_sem_texto_da_nota(self) -> None:
        estado = novo_estado(self.notas, "hash-do-golden")
        estado["votos"][0] = [self.errada] * NUM_VOTOS
        tabela = relatorio(self.notas, estado)
        self.assertIn(
            f"| 1 | {self.certa} | {self.errada}×5 | {self.errada} | 5/5 (100%) | não |",
            tabela,
        )
        self.assertIn("| 5/5 (100%) | 0 | 1 | 0 |", tabela)
        self.assertNotIn(self.notas[0]["texto"], tabela)

    def test_retoma_sem_repetir_votos_e_sem_guardar_texto(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "estado.json"
            estado = novo_estado(self.notas, "hash-do-golden")
            chamadas = 0

            def interromper(_texto: str) -> str:
                nonlocal chamadas
                chamadas += 1
                if chamadas == 3:
                    raise RuntimeError("interrupção simulada")
                return self.certa

            with contextlib.redirect_stdout(io.StringIO()) as saida:
                with self.assertRaises(RuntimeError):
                    recolher_votos(self.notas, estado, caminho, interromper, 0)
            self.assertEqual(chamadas, 3)
            self.assertEqual(len(estado["votos"][0]), 2)
            self.assertNotIn(
                self.notas[0]["texto"], caminho.read_text(encoding="utf-8")
            )
            self.assertNotIn(self.notas[0]["texto"], saida.getvalue())

            retomado = carregar_estado(caminho, self.notas, "hash-do-golden")
            faltavam = 0

            def completar(_texto: str) -> str:
                nonlocal faltavam
                faltavam += 1
                return self.errada

            with contextlib.redirect_stdout(io.StringIO()):
                recolher_votos(self.notas, retomado, caminho, completar, 0)
            self.assertEqual(faltavam, 3)
            self.assertEqual(retomado["votos"][0], [self.certa] * 2 + [self.errada] * 3)
            self.assertNotIn(self.notas[0]["texto"], relatorio(self.notas, retomado))

    def test_estado_invalido_ou_golden_alterado_e_rejeitado(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "estado.json"
            caminho.write_text(
                json.dumps(novo_estado(self.notas, "antigo")), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "incompatível"):
                carregar_estado(caminho, self.notas, "novo")
            caminho.write_text(
                json.dumps(
                    {**novo_estado(self.notas, "novo"), "votos": [["inventada"]]}
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "incompatível"):
                carregar_estado(caminho, self.notas, "novo")

    def test_digest_do_golden_independe_de_lf_ou_crlf(self) -> None:
        texto = json.dumps(self.notas, ensure_ascii=False, indent=2) + "\n"
        self.assertEqual(
            digest_golden(json.loads(texto)),
            digest_golden(json.loads(texto.replace("\n", "\r\n"))),
        )

    def test_chamada_usa_prompt_schema_modelo_e_temperatura(self) -> None:
        class ClienteFalso:
            def __init__(self, categoria: str) -> None:
                self.argumentos = None
                self.categoria = categoria
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=self.criar)
                )

            def criar(self, **kwargs: object) -> SimpleNamespace:
                self.argumentos = kwargs
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=json.dumps({"categoria": self.categoria})
                            )
                        )
                    ]
                )

        cliente = ClienteFalso(self.certa)
        self.assertEqual(classificar_amostra(cliente, "uma nota"), self.certa)  # type: ignore[arg-type]
        self.assertEqual(cliente.argumentos["model"], app.MODEL)
        self.assertEqual(cliente.argumentos["temperature"], TEMPERATURA)
        self.assertEqual(cliente.argumentos["response_format"], app.FORMATO_CATEGORIA)
        self.assertEqual(
            cliente.argumentos["messages"][1]["content"], app.criar_prompt("uma nota")
        )

    def test_relatorio_versionado_funciona_sem_estado_ou_chave(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            with (
                mock.patch.object(
                    avaliar_acordo, "ESTADO", Path(pasta) / "inexistente.json"
                ),
                mock.patch.object(
                    sys, "argv", ["avaliar_acordo.py", "--apenas-relatorio"]
                ),
                mock.patch.dict(os.environ, {"NVIDIA_API_KEY": ""}),
                contextlib.redirect_stdout(io.StringIO()) as saida,
            ):
                self.assertEqual(avaliar_acordo.main(), 0)
        self.assertEqual(
            sum(
                bool(re.match(r"\| \d+ \|", linha))
                for linha in saida.getvalue().splitlines()
            ),
            34,
        )


if __name__ == "__main__":
    unittest.main()
