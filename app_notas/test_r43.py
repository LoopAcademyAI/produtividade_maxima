"""Testes offline do A/B com crítico condicional R4.3."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import app
import avaliar_critico
from avaliar_acordo import digest_golden
from avaliar_critico import (
    CORRIDAS,
    carregar_estado,
    classificar,
    metricas_corrida,
    novo_estado,
    recolher,
    relatorio,
)


class TestarCritico(unittest.TestCase):
    def setUp(self) -> None:
        self.certa, self.errada = app.CATEGORIES[:2]

    def test_critico_so_e_chamado_com_acordo_parcial(self) -> None:
        notas = [
            {"texto": "nota privada estável", "categoria": self.certa},
            {"texto": "nota privada duvidosa", "categoria": self.errada},
        ]
        estado = novo_estado(notas, "digest")
        contagens = {nota["texto"]: 0 for nota in notas}
        chamadas_critico = []

        def modelo(texto: str, votos: list[str] | None) -> tuple[str, int, int]:
            if votos is not None:
                chamadas_critico.append((texto, votos[:]))
                return self.errada, 20, 2
            indice = contagens[texto]
            contagens[texto] += 1
            if texto == notas[0]["texto"]:
                return self.certa, 10, 1
            return (self.errada if indice % 5 == 4 else self.certa), 10, 1

        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "estado.json"
            with contextlib.redirect_stdout(io.StringIO()) as saida:
                recolher(notas, estado, caminho, modelo, 0)
            self.assertNotIn(notas[0]["texto"], caminho.read_text(encoding="utf-8"))
            self.assertNotIn(notas[1]["texto"], saida.getvalue())
        self.assertEqual(len(chamadas_critico), CORRIDAS)
        self.assertTrue(all(len(votos) == 5 for _, votos in chamadas_critico))
        for corrida in estado["corridas"]:
            m = metricas_corrida(notas, corrida)
            self.assertEqual((m["acertos_a"], m["acertos_b"]), (1, 2))
            self.assertEqual((m["entrada_a"], m["saida_a"]), (100, 10))
            self.assertEqual((m["entrada_b"], m["saida_b"]), (120, 12))
            self.assertEqual(
                (m["criticos"], m["corrigidos"], m["prejudicados"]), (1, 1, 0)
            )
            self.assertEqual(m["mudancas"], 1)
            self.assertEqual(m["erros_consenso"], 0)
        tabela = relatorio(notas, estado)
        self.assertIn("Custo adicional do crítico: 22.00 ± 0.00", tabela)
        self.assertIn("Diferença B−A: 50.00 ± 0.00", tabela)

    def test_retoma_sem_repetir_votos(self) -> None:
        notas = [{"texto": "nota privada", "categoria": self.certa}]
        estado = novo_estado(notas, "digest")
        feitas = 0

        def interromper(_texto: str, _votos: list[str] | None) -> tuple[str, int, int]:
            nonlocal feitas
            feitas += 1
            if feitas == 3:
                raise RuntimeError("interrupção simulada")
            return self.certa, 7, 1

        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "estado.json"
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):
                    recolher(notas, estado, caminho, interromper, 0)
            retomado = carregar_estado(caminho, notas, "digest")
            self.assertEqual(len(retomado["corridas"][0][0]["votos"]), 2)
            restante = 0

            def completar(_texto: str, votos: list[str] | None) -> tuple[str, int, int]:
                nonlocal restante
                self.assertIsNone(votos)
                restante += 1
                return self.certa, 7, 1

            with contextlib.redirect_stdout(io.StringIO()):
                recolher(notas, retomado, caminho, completar, 0)
            self.assertEqual(restante, CORRIDAS * 5 - 2)
            self.assertEqual(
                metricas_corrida(notas, retomado["corridas"][0])["entrada_a"], 35
            )

    def test_erro_com_consenso_nao_chega_ao_critico(self) -> None:
        notas = [{"texto": "nota privada", "categoria": self.certa}]
        estado = novo_estado(notas, "digest")
        item = estado["corridas"][0][0]
        item["votos"] = [self.errada] * 5
        item["entrada_votos"] = 50
        item["saida_votos"] = 5
        m = metricas_corrida(notas, estado["corridas"][0])
        self.assertEqual((m["acertos_a"], m["acertos_b"], m["criticos"]), (0, 0, 0))
        self.assertEqual(m["mudancas"], 0)
        self.assertEqual(m["erros_consenso"], 1)

    def test_estado_rejeita_golden_diferente_e_critico_indevido(self) -> None:
        notas = [{"texto": "nota privada", "categoria": self.certa}]
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "estado.json"
            dados = novo_estado(notas, "anterior")
            caminho.write_text(json.dumps(dados), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "incompatível"):
                carregar_estado(caminho, notas, "novo")
            dados = novo_estado(notas, "novo")
            dados["corridas"][0][0]["votos"] = [self.certa] * 5
            dados["corridas"][0][0]["critico"] = {
                "categoria": self.errada,
                "entrada": 10,
                "saida": 1,
            }
            caminho.write_text(json.dumps(dados), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Crítico inválido"):
                carregar_estado(caminho, notas, "novo")

    def test_chamada_modelo_usa_schema_e_conta_tokens(self) -> None:
        class ClienteFalso:
            def __init__(self, categoria: str) -> None:
                self.pedidos = []
                self.categoria = categoria
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=self.criar)
                )

            def criar(self, **kwargs: object) -> SimpleNamespace:
                self.pedidos.append(kwargs)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=json.dumps({"categoria": self.categoria})
                            )
                        )
                    ],
                    usage=SimpleNamespace(prompt_tokens=14, completion_tokens=2),
                )

        cliente = ClienteFalso(self.certa)
        self.assertEqual(
            classificar(cliente, "nota privada", None), (self.certa, 14, 2)
        )  # type: ignore[arg-type]
        self.assertEqual(
            classificar(cliente, "nota privada", [self.errada] * 4 + [self.certa]),  # type: ignore[arg-type]
            (self.certa, 14, 2),
        )
        self.assertEqual(
            [pedido["temperature"] for pedido in cliente.pedidos], [0.8, 0]
        )
        self.assertTrue(
            all(
                pedido["response_format"] == app.FORMATO_CATEGORIA
                for pedido in cliente.pedidos
            )
        )
        self.assertIn(
            "Categoria candidata", cliente.pedidos[1]["messages"][1]["content"]
        )

    def test_relatorio_versionado_nao_exige_chave_ou_rede(self) -> None:
        notas = [{"texto": "nota privada", "categoria": self.certa}]
        estado = novo_estado(notas, digest_golden(notas))
        for corrida in estado["corridas"]:
            corrida[0]["votos"] = [self.certa] * 5
            corrida[0]["entrada_votos"] = 50
            corrida[0]["saida_votos"] = 5
        with tempfile.TemporaryDirectory() as pasta:
            with (
                mock.patch.object(
                    avaliar_critico, "ESTADO", Path(pasta) / "ausente.json"
                ),
                mock.patch.object(
                    avaliar_critico, "RESULTADOS", Path(pasta) / "resultados.json"
                ),
                mock.patch.object(
                    avaliar_critico, "carregar_golden", return_value=notas
                ),
                mock.patch.object(
                    sys, "argv", ["avaliar_critico.py", "--apenas-relatorio"]
                ),
                mock.patch.dict(os.environ, {"NVIDIA_API_KEY": ""}),
                contextlib.redirect_stdout(io.StringIO()) as saida,
            ):
                avaliar_critico.guardar_estado(avaliar_critico.RESULTADOS, estado)
                self.assertEqual(avaliar_critico.main(), 0)
        self.assertIn("A: acerto 100.00 ± 0.00%", saida.getvalue())
        self.assertNotIn(notas[0]["texto"], saida.getvalue())

    def test_resposta_sem_contagem_de_tokens_nao_e_aceite(self) -> None:
        resposta = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({"categoria": self.certa})
                    )
                )
            ],
            usage=None,
        )
        cliente = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_: resposta)
            )
        )
        with self.assertRaisesRegex(ValueError, "tokens"):
            classificar(cliente, "nota privada", None)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
