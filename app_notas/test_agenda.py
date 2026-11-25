"""R2.2: extrator, migração e API, com SQLite e modelo simulado, sem rede."""

import json
import os
import sqlite3
import tempfile
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

tempdir = tempfile.TemporaryDirectory()
os.environ["NOTAS_SQLITE"] = str(Path(tempdir.name) / "notas.db")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

from fastapi.testclient import TestClient  # noqa: E402
from openai import OpenAIError  # noqa: E402

import app  # noqa: E402
import db  # noqa: E402
from agenda import extrair_quando  # noqa: E402
from agenda_evento import (  # noqa: E402
    extrair_evento_agenda,
    validar_resposta_modelo,
)
from resolver_data import resolver_quando  # noqa: E402


class ClienteFalso:
    def __init__(self, conteudo):
        resposta = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=conteudo))]
        )
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: resposta)
        )


class ClienteComErro:
    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.criar))

    @staticmethod
    def criar(**kwargs):
        raise OpenAIError("falha simulada")


def criar_payload_modelo(evento, data, hora, evidencia, estado="agendado"):
    return json.dumps(
        {
            "evento": evento,
            "expressao_data": data,
            "expressao_hora": hora,
            "evidencia": evidencia,
            "estado": estado,
        },
        ensure_ascii=False,
    )


def main():
    ref = datetime.fromisoformat("2026-11-23T10:00:00")
    assert extrair_quando("Jantar Sabádp as 21:30", ref) == "2026-11-28T21:30:00"
    assert extrair_quando("Marcar reunião", ref) is None
    assert extrair_quando("Marcar reunião às 21:30", ref) is None
    assert extrair_quando("Visitar a quinta da família", ref) is None
    assert extrair_quando("Visitar a quinta", ref) is None
    assert extrair_quando("Preparar a sexta consulta", ref) is None
    assert extrair_quando("Almoço na quinta-feira", ref) == "2026-11-26"
    assert extrair_quando("Não há reunião sábado", ref) is None
    assert extrair_quando("Reunião amanhã ou sábado", ref) is None
    assert extrair_quando("Reunião 31/02/2026", ref) is None
    assert extrair_quando("Reunião amanhã às 25:70", ref) is None
    assert extrair_quando("Reunião próximo sábado", ref) is None
    assert extrair_quando("Reunião amanhã às 9h ou 10h", ref) is None

    # O resolvedor local recebe excertos literais, sem pedir ao modelo que calcule ISO.
    assert resolver_quando("Sabádp", "as 21:30", ref) == "2026-11-28T21:30:00"
    assert resolver_quando("19/05/2027", None, ref) == "2027-05-19"
    assert resolver_quando("31/02/2027", None, ref) is None

    nota = "A consulta de cardiologia ficou marcada para quarta-feira às 09:40."
    bruto = criar_payload_modelo(
        "consulta de cardiologia",
        "quarta-feira",
        "às 09:40",
        "consulta de cardiologia ficou marcada para quarta-feira às 09:40",
    )
    resultado = extrair_evento_agenda(nota, "2027-05-10T10:00:00", ClienteFalso(bruto))
    assert resultado.estado == "ok"
    assert resultado.quando == "2027-05-12T09:40:00"
    assert (
        extrair_evento_agenda(nota, ref, ClienteComErro()).estado
        == "erro_modelo_OpenAIError"
    )
    with patch.dict(os.environ, {"NVIDIA_API_KEY": ""}):
        assert extrair_evento_agenda(nota, ref).estado == "chave_em_falta"

    # Ambiguidade, resposta não literal e data fora do escopo falham em segurança.
    sem_data = criar_payload_modelo("Jantar", None, None, None, estado="incerto")
    assert (
        extrair_evento_agenda(
            "Jantar talvez sexta ou sábado?", ref, ClienteFalso(sem_data)
        ).quando
        is None
    )
    nao_literal = criar_payload_modelo(
        "consulta",
        "sexta-feira",
        None,
        "consulta marcada para sexta-feira",
    )
    assert (
        validar_resposta_modelo(
            nao_literal, "A consulta ficou marcada amanhã.", ref
        ).estado
        == "evidencia_nao_literal"
    )
    fora_escopo = criar_payload_modelo(
        "Consulta",
        "sexta-feira",
        None,
        "Consulta; sexta-feira",
    )
    assert (
        validar_resposta_modelo(
            fora_escopo,
            "Consulta; sexta-feira.",
            ref,
        ).estado
        == "fora_do_mesmo_escopo"
    )
    data_invalida = criar_payload_modelo(
        "reunião",
        "31/02/2027",
        None,
        "reunião está marcada para 31/02/2027",
    )
    assert (
        validar_resposta_modelo(
            data_invalida, "A reunião está marcada para 31/02/2027.", ref
        ).estado
        == "data_nao_resolvida_localmente"
    )
    assert validar_resposta_modelo("não é JSON", nota, ref).estado == "json_invalido"

    # Simula uma base instalada antes da introdução de `quando`.
    with closing(sqlite3.connect(os.environ["NOTAS_SQLITE"])) as conn, conn:
        conn.execute(
            "CREATE TABLE notas (id TEXT PRIMARY KEY, utilizador TEXT NOT NULL, texto TEXT NOT NULL, categoria TEXT NOT NULL, criada_em TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO notas VALUES ('antiga', 'ana', 'nota antiga', 'agenda', '2026-01-01')"
        )
    assert db.listar("ana")[0]["quando"] is None
    assert db.listar("ana")[0]["texto"] == "nota antiga"

    ana, rui = {"X-Utilizador": str(uuid.uuid4())}, {"X-Utilizador": str(uuid.uuid4())}
    with TestClient(app.app) as client:
        with (
            patch.object(app, "classificar_texto", return_value="agenda"),
            patch.object(
                app,
                "extrair_evento_agenda",
                side_effect=[
                    SimpleNamespace(estado="ok", quando="2026-12-10T21:30:00"),
                    SimpleNamespace(estado="sem_data", quando=None),
                ],
            ) as extrair_agenda,
        ):
            resposta = client.post(
                "/api/notas", json={"texto": "Jantar 2026-12-10 às 21:30"}, headers=ana
            )
            assert resposta.status_code == 201
            assert resposta.json()["quando"] == "2026-12-10T21:30:00"
            resposta = client.post(
                "/api/notas", json={"texto": "Combinar reunião"}, headers=ana
            )
            assert resposta.json()["quando"] is None
            assert extrair_agenda.call_count == 2
        with (
            patch.object(app, "classificar_texto", return_value="tarefa"),
            patch.object(app, "extrair_evento_agenda") as extrair_nao_agenda,
        ):
            resposta = client.post(
                "/api/notas", json={"texto": "Comprar pão amanhã"}, headers=ana
            )
            assert resposta.json()["quando"] is None
            extrair_nao_agenda.assert_not_called()
        notas = client.get("/api/notas", headers=ana).json()
        assert len(notas) == 3
        assert any(n["quando"] == "2026-12-10T21:30:00" for n in notas)
        assert client.get("/api/notas", headers=rui).json() == []
    print("OK: extração, migração SQLite, API e isolamento.")


if __name__ == "__main__":
    main()
