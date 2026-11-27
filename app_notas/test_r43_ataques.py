"""Testes offline da avaliação adversarial do crítico R4.3."""

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
import avaliar_ataques_critico as ataques
from avaliar_acordo import digest_golden
from avaliar_critico import classificar


class TestarAtaquesCritico(unittest.TestCase):
    def setUp(self) -> None:
        self.casos = ataques.carregar_casos()

    def test_seis_casos_sinteticos_e_rejeicao_de_dataset_alterado(self) -> None:
        self.assertEqual(len(self.casos), 6)
        self.assertEqual(len({caso["id"] for caso in self.casos}), 6)
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "casos.json"
            repetidos = self.casos[:]
            repetidos[-1] = {**repetidos[-1], "id": repetidos[0]["id"]}
            caminho.write_text(json.dumps(repetidos), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "inválidos"):
                ataques.carregar_casos(caminho)

    def test_papel_falso_fica_na_nota_e_marcadores_sao_escapados(self) -> None:
        pedidos = []

        def criar(**kwargs: object) -> SimpleNamespace:
            pedidos.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"categoria":"tarefa"}')
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=20, completion_tokens=2),
            )

        cliente = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=criar))
        )
        caso_papel = next(c for c in self.casos if c["id"] == "papel_sistema")
        caso_marcador = next(c for c in self.casos if c["id"] == "fecho_marcador")
        for caso in (caso_papel, caso_marcador):
            votos = [caso["esperada"]] * 3 + [caso["alvo"]] * 2
            classificar(cliente, caso["ataque"], votos)  # type: ignore[arg-type]
        for pedido in pedidos:
            self.assertEqual(pedido["temperature"], 0)
            self.assertEqual(pedido["response_format"], app.FORMATO_CATEGORIA)
            self.assertNotIn("tools", pedido)
            self.assertEqual(
                [m["role"] for m in pedido["messages"]], ["system", "user"]
            )
        self.assertNotIn("[im_start]", pedidos[0]["messages"][0]["content"])
        self.assertIn("[im_start]system", pedidos[0]["messages"][1]["content"])
        pergunta = pedidos[1]["messages"][1]["content"]
        self.assertEqual(pergunta.count("<nota_usuario>"), 1)
        self.assertEqual(pergunta.count("</nota_usuario>"), 1)
        self.assertIn("&lt;/nota_usuario&gt;", pergunta)

    def test_resposta_com_campo_extra_e_rejeitada(self) -> None:
        cliente = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_kwargs: SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                message=SimpleNamespace(
                                    content='{"categoria":"pessoal","chave":"segredo-falso"}'
                                )
                            )
                        ],
                        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10),
                    )
                )
            )
        )
        caso = next(c for c in self.casos if c["id"] == "pedido_de_chave")
        votos = [caso["esperada"]] * 3 + [caso["alvo"]] * 2
        with self.assertRaisesRegex(ValueError, "Resposta ou tokens"):
            classificar(cliente, caso["ataque"], votos)  # type: ignore[arg-type]

    def test_retoma_regista_falhas_sem_guardar_textos(self) -> None:
        caso = self.casos[0]
        estado = ataques.novo_estado([caso], "digest")
        chamadas = 0

        def interromper(_texto: str, votos: list[str]) -> tuple[str, int, int]:
            nonlocal chamadas
            self.assertEqual(votos, [caso["esperada"]] * 3 + [caso["alvo"]] * 2)
            chamadas += 1
            if chamadas == 3:
                raise RuntimeError("interrupção simulada")
            return caso["esperada"], 10, 1

        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "progresso.json"
            with contextlib.redirect_stdout(io.StringIO()) as saida:
                with self.assertRaises(RuntimeError):
                    ataques.recolher([caso], estado, caminho, interromper, 0)
            bruto = caminho.read_text(encoding="utf-8")
            self.assertNotIn(caso["controlo"], bruto)
            self.assertNotIn(caso["ataque"], bruto)
            self.assertNotIn(caso["ataque"], saida.getvalue())
            retomado = ataques.carregar_estado(caminho, [caso], "digest")
            self.assertEqual(len(retomado["resultados"][0]["controlo"]), 2)
            restantes = 0

            def completar(texto: str, _votos: list[str]) -> tuple[str, int, int]:
                nonlocal restantes
                restantes += 1
                return (
                    (caso["esperada"] if texto == caso["controlo"] else caso["alvo"]),
                    10,
                    1,
                )

            with contextlib.redirect_stdout(io.StringIO()):
                ataques.recolher([caso], retomado, caminho, completar, 0)
            self.assertEqual(restantes, 4)
            tabela = ataques.relatorio([caso], retomado)
            self.assertIn("Controlo correto: 3/3", tabela)
            self.assertIn("Ataque correto: 0/3", tabela)
            self.assertIn("Alvo da injeção escolhido: 3/3", tabela)
            self.assertNotIn(caso["controlo"], tabela)

    def test_estado_rejeita_hash_e_resposta_invalida(self) -> None:
        caso = self.casos[0]
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "progresso.json"
            estado = ataques.novo_estado([caso], "antigo")
            ataques.guardar_estado(caminho, estado)
            with self.assertRaisesRegex(ValueError, "incompatível"):
                ataques.carregar_estado(caminho, [caso], "novo")
            estado = ataques.novo_estado([caso], "novo")
            estado["resultados"][0]["ataque"] = [
                {"categoria": "inventada", "entrada": 10, "saida": 1}
            ]
            ataques.guardar_estado(caminho, estado)
            with self.assertRaisesRegex(ValueError, "Respostas inválidas"):
                ataques.carregar_estado(caminho, [caso], "novo")

    def test_relatorio_offline_sem_chave_ou_rede(self) -> None:
        caso = self.casos[0]
        estado = ataques.novo_estado([caso], digest_golden([caso]))
        for variante in ("controlo", "ataque"):
            estado["resultados"][0][variante] = [
                {"categoria": caso["esperada"], "entrada": 10, "saida": 1}
                for _ in range(ataques.REPETICOES)
            ]
        with tempfile.TemporaryDirectory() as pasta:
            with (
                mock.patch.object(ataques, "ESTADO", Path(pasta) / "ausente.json"),
                mock.patch.object(
                    ataques, "RESULTADOS", Path(pasta) / "resultado.json"
                ),
                mock.patch.object(ataques, "carregar_casos", return_value=[caso]),
                mock.patch.object(
                    sys, "argv", ["avaliar_ataques_critico.py", "--apenas-relatorio"]
                ),
                mock.patch.dict(os.environ, {"NVIDIA_API_KEY": ""}),
                contextlib.redirect_stdout(io.StringIO()) as saida,
            ):
                ataques.guardar_estado(ataques.RESULTADOS, estado)
                self.assertEqual(ataques.main(), 0)
        self.assertIn("Ataque correto: 3/3", saida.getvalue())
        self.assertNotIn(caso["ataque"], saida.getvalue())


if __name__ == "__main__":
    unittest.main()
