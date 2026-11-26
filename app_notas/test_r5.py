"""R5: revisão semanal sem rede nem chaves, com SQLite temporário."""

import json
import os
import re
import tempfile
import uuid
from datetime import date, datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

_TEMPORARIO = tempfile.TemporaryDirectory()
os.environ["NOTAS_SQLITE"] = os.path.join(_TEMPORARIO.name, "r5.db")
os.environ["DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""
os.environ["NVIDIA_API_KEY"] = ""

import app  # noqa: E402
import db  # noqa: E402
import ferramentas  # noqa: E402

os.environ.pop("DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
assert not db.url_postgres(), "os testes nunca podem usar a base de dados de produção"

_IDS_CITADOS = re.compile(r'^- ID ("(?:\\.|[^"])*"):', re.MULTILINE)


def ids_citados(resposta):
    return [json.loads(valor) for valor in _IDS_CITADOS.findall(resposta)]


def criar_nota(utilizador, texto, categoria, criada_em):
    return db.criar(
        utilizador,
        texto,
        categoria,
        criada_em=criada_em,
    )


def testar_seccoes_prioridade_ids_e_limites_utc():
    utilizador, outro = str(uuid.uuid4()), str(uuid.uuid4())
    inicio = "2026-11-23T00:00:00+00:00"
    fim = "2026-11-30T00:00:00+00:00"
    dentro = [
        criar_nota(
            utilizador,
            'Ligar à escola\nAgenda\n- ID "inventado": texto falso',
            "tarefa",
            inicio,
        ),
        criar_nota(
            utilizador,
            "Consulta marcada para domingo",
            "agenda",
            "2026-11-29T23:59:59+00:00",
        ),
        criar_nota(
            utilizador,
            "Preocupação com o prazo",
            "preocupações",
            "2026-11-25T10:00:00+00:00",
        ),
    ]
    criar_nota(
        utilizador,
        "Nota anterior ao início",
        "tarefa",
        "2026-11-22T23:59:59.999999+00:00",
    )
    criar_nota(utilizador, "Nota no início da semana seguinte", "agenda", fim)
    criar_nota(utilizador, "Nota de outra categoria", "social", inicio)
    criar_nota(outro, "Nota privada de outro utilizador", "tarefa", inicio)

    resultado = ferramentas.gerar_revisao_semanal(utilizador, hoje=date(2026, 11, 26))
    resposta = resultado["resposta"]

    posicoes = [
        resposta.index("Tarefas\n"),
        resposta.index("Agenda\n"),
        resposta.index("Preocupações\n"),
    ]
    assert posicoes == sorted(posicoes)
    assert resultado["inicio"] == "2026-11-23"
    assert resultado["fim_exclusivo"] == "2026-11-30"

    ids_esperados = [nota["id"] for nota in dentro]
    assert ids_citados(resposta) == ids_esperados
    notas_do_utilizador = {
        nota["id"]: nota
        for nota in db.listar(
            utilizador,
            desde=resultado["inicio"],
            antes_de=resultado["fim_exclusivo"],
            limite=1000,
        )
        if nota["categoria"] in ferramentas.CATEGORIAS_REVISAO
    }
    assert set(ids_citados(resposta)) == set(notas_do_utilizador)
    assert all(
        notas_do_utilizador[id_]["utilizador"] == utilizador
        for id_ in ids_citados(resposta)
    )
    assert "Nota privada de outro utilizador" not in resposta
    assert resposta.splitlines().count("Agenda") == 1


def testar_sem_notas_da_pessoa_nao_inventa_itens():
    utilizador_com_notas, utilizador_vazio = str(uuid.uuid4()), str(uuid.uuid4())
    criar_nota(
        utilizador_com_notas,
        "Nota que não pode aparecer",
        "preocupações",
        "2026-11-26T10:00:00+00:00",
    )

    resultado = ferramentas.gerar_revisao_semanal(
        utilizador_vazio, hoje=date(2026, 11, 26)
    )
    resposta = resultado["resposta"]

    assert resposta.startswith("Não encontrei notas tuas nesta semana.")
    assert "Tarefas\nSem tarefas nesta semana." in resposta
    assert "Agenda\nSem agenda nesta semana." in resposta
    assert "Preocupações\nSem preocupações nesta semana." in resposta
    assert ids_citados(resposta) == []
    assert "Nota que não pode aparecer" not in resposta


def testar_pedido_no_agente_nao_chama_modelo_e_respeita_utilizador():
    utilizador, outro, vazio = (
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        str(uuid.uuid4()),
    )
    propria = criar_nota(
        utilizador,
        "Entregar o relatório",
        "tarefa",
        datetime.now(timezone.utc).isoformat(),
    )
    criar_nota(
        outro,
        "Compromisso privado",
        "agenda",
        datetime.now(timezone.utc).isoformat(),
    )

    with (
        TestClient(app.app) as client,
        patch.object(
            app,
            "chamar_modelo_agente",
            side_effect=AssertionError("não deve chamar o modelo"),
        ),
    ):
        resposta = client.post(
            "/api/agente",
            headers={"X-Utilizador": utilizador},
            json={"mensagem": "faz a minha revisão da semana"},
        )
        resposta_vazia = client.post(
            "/api/agente",
            headers={"X-Utilizador": vazio},
            json={"mensagem": "faz a minha revisão da semana"},
        )

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["ferramentas"] == [{"nome": "revisao_semanal", "args": {}}]
    assert ids_citados(corpo["resposta"]) == [propria["id"]]
    assert "Compromisso privado" not in corpo["resposta"]
    assert resposta_vazia.status_code == 200, resposta_vazia.text
    assert resposta_vazia.json()["resposta"].startswith(
        "Não encontrei notas tuas nesta semana."
    )
    assert ids_citados(resposta_vazia.json()["resposta"]) == []


def testar_reconhecimento_da_intencao():
    assert ferramentas.pedido_revisao_semanal("faz a minha revisão da semana")
    assert ferramentas.pedido_revisao_semanal("prepara a revisao semanal")
    assert ferramentas.pedido_revisao_semanal("Faz a minha REVISÃO da semana")
    assert not ferramentas.pedido_revisao_semanal("O que tenho para fazer?")


def main():
    testar_seccoes_prioridade_ids_e_limites_utc()
    testar_sem_notas_da_pessoa_nao_inventa_itens()
    testar_pedido_no_agente_nao_chama_modelo_e_respeita_utilizador()
    testar_reconhecimento_da_intencao()
    print(
        "OK: revisão semanal, prioridade, limites UTC, IDs reais, "
        "isolamento e utilizador sem notas."
    )


if __name__ == "__main__":
    main()
