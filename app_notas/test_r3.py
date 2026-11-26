"""R3.1: propostas de reorganização persistidas e aprovação individual."""

import io
import json
import logging
import os
import tempfile
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

_TEMPORARIO = tempfile.TemporaryDirectory()
os.environ["NOTAS_SQLITE"] = os.path.join(_TEMPORARIO.name, "r3.db")
os.environ["DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""
os.environ["NVIDIA_API_KEY"] = ""

import app  # noqa: E402
import db  # noqa: E402
import ferramentas  # noqa: E402

ANA = "11111111-1111-4111-8111-111111111111"
RUI = "22222222-2222-4222-8222-222222222222"
HEADERS_ANA = {"X-Utilizador": ANA}
HEADERS_RUI = {"X-Utilizador": RUI}


def limpar_bd():
    with db.ligacao() as sql:
        sql("DELETE FROM propostas_categoria")
        sql("DELETE FROM notas")


def preparar_notas(utilizador=ANA):
    return [
        db.criar(utilizador, f"Nota de teste {indice}", categoria)
        for indice, categoria in enumerate(
            ("tarefa", "social", "ideia", "pessoal", "trabalho")
        )
    ]


def agente_simulado(ids, categorias):
    chamadas = []

    def modelo(mensagens, _request_id):
        chamadas.append(mensagens)
        respostas_tool = [
            mensagem["content"]
            for mensagem in mensagens
            if mensagem.get("role") == "tool"
        ]
        if not respostas_tool:
            return {
                "texto": "",
                "chamadas": [{"id": "listar-1", "nome": "listar_notas", "args": {}}],
            }

        dados = json.loads(respostas_tool[-1])
        if "notas" in dados:
            propostas = [
                {"nota_id": nota_id, "categoria": categoria}
                for nota_id, categoria in zip(ids, categorias)
            ]
            return {
                "texto": "",
                "chamadas": [
                    {
                        "id": "propor-1",
                        "nome": "propor_alteracoes_categoria",
                        "args": {"propostas": propostas},
                    }
                ],
            }
        return {"texto": "Preparei sugestões para rever.", "chamadas": []}

    return modelo, chamadas


def criar_propostas_pelo_agente(client, notas, categorias):
    modelo, chamadas = agente_simulado([nota["id"] for nota in notas], categorias)
    with patch.object(app, "chamar_modelo_agente", side_effect=modelo):
        resposta = client.post(
            "/api/agente",
            headers=HEADERS_ANA,
            json={"mensagem": "Arruma as minhas notas", "conversa": str(uuid.uuid4())},
        )
    assert resposta.status_code == 200, resposta.text
    return resposta.json(), chamadas


def testar_proposta_persistida_sem_mudar_notas():
    limpar_bd()
    notas = preparar_notas()
    categorias = ("agenda", "tarefa", "social", "ideia", "pessoal")
    antes = {nota["id"]: nota["categoria"] for nota in db.listar(ANA)}

    with TestClient(app.app) as client:
        corpo, chamadas = criar_propostas_pelo_agente(client, notas, categorias)

    assert corpo["pendente"] is not None
    assert corpo["pendente"]["total"] == 5
    assert len(corpo["pendente"]["propostas"]) == 5
    assert all(p["estado"] == "pendente" for p in corpo["pendente"]["propostas"])
    assert any("propor_alteracoes_categoria" in str(m) for m in chamadas)
    depois = {nota["id"]: nota["categoria"] for nota in db.listar(ANA)}
    assert depois == antes, "A proposta não pode alterar notas."
    assert len(db.listar_propostas_categoria(ANA)) == 5


def testar_categorias_invalidas_iguais_e_notas_alheias_descartadas():
    limpar_bd()
    nota = db.criar(ANA, "Preparar reunião", "tarefa")
    nota_rui = db.criar(RUI, "Nota do Rui", "social")
    entradas = [
        {"nota_id": nota["id"], "categoria": "inventada"},
        {"nota_id": nota["id"], "categoria": "tarefa"},
        {"nota_id": nota_rui["id"], "categoria": "agenda"},
        {"nota_id": "id-inexistente", "categoria": "agenda"},
        {"nota_id": nota["id"], "categoria": "agenda", "extra": "ignorar"},
        None,
    ]

    resultado = ferramentas.propor_alteracoes_categoria(ANA, entradas)
    assert resultado == {"lote_id": None, "total": 0, "propostas": []}
    assert db.listar_propostas_categoria(ANA) == []
    assert db.listar(ANA)[0]["categoria"] == "tarefa"

    resultado_valido = ferramentas.propor_alteracoes_categoria(
        ANA, [{"nota_id": nota["id"], "categoria": "agenda"}]
    )
    assert resultado_valido["total"] == 1
    assert resultado_valido["propostas"][0]["nota_id"] == nota["id"]
    assert db.listar(ANA)[0]["categoria"] == "tarefa"


def testar_aprovacao_e_rejeicao_individuais_apos_restart():
    limpar_bd()
    notas = preparar_notas()
    categorias = ("agenda", "tarefa", "social", "ideia", "pessoal")

    with TestClient(app.app) as client:
        corpo, _ = criar_propostas_pelo_agente(client, notas, categorias)
        ids_propostas = [p["id"] for p in corpo["pendente"]["propostas"]]
        assert (
            len(client.get("/api/propostas/pendentes", headers=HEADERS_ANA).json()) == 5
        )

    # Fechar e reabrir o app simula deploy/restart; o estado tem de vir da base de dados.
    with TestClient(app.app) as client:
        pendentes = client.get("/api/propostas/pendentes", headers=HEADERS_ANA)
        assert pendentes.status_code == 200
        assert {p["id"] for p in pendentes.json()} == set(ids_propostas)

        aprovadas = ids_propostas[:2]
        rejeitadas = ids_propostas[2:]
        for proposta_id in aprovadas:
            resposta = client.post(
                f"/api/propostas/{proposta_id}/aprovar", headers=HEADERS_ANA
            )
            assert resposta.status_code == 200, resposta.text
        for proposta_id in rejeitadas:
            resposta = client.post(
                f"/api/propostas/{proposta_id}/rejeitar", headers=HEADERS_ANA
            )
            assert resposta.status_code == 204, resposta.text

        estado_final = {nota["id"]: nota["categoria"] for nota in db.listar(ANA)}
        esperado = {nota["id"]: categoria for nota, categoria in zip(notas, categorias)}
        for proposta_id, nota in zip(ids_propostas, notas):
            if proposta_id not in aprovadas:
                esperado[nota["id"]] = nota["categoria"]
        assert estado_final == esperado, "Só as duas propostas aprovadas devem mudar."
        assert client.get("/api/propostas/pendentes", headers=HEADERS_ANA).json() == []


def testar_isolamento_repeticao_e_proposta_desatualizada():
    limpar_bd()
    nota = db.criar(ANA, "Nota privada", "tarefa")
    proposta = ferramentas.propor_alteracoes_categoria(
        ANA, [{"nota_id": nota["id"], "categoria": "agenda"}]
    )["propostas"][0]
    repetida = ferramentas.propor_alteracoes_categoria(
        ANA, [{"nota_id": nota["id"], "categoria": "social"}]
    )
    assert repetida["propostas"] == []
    assert len(db.listar_propostas_categoria(ANA)) == 1

    with TestClient(app.app) as client:
        assert client.get("/api/propostas/pendentes", headers=HEADERS_RUI).json() == []
        assert client.get("/api/propostas/pendentes").status_code == 400
        assert (
            client.post(
                f"/api/propostas/{proposta['id']}/aprovar", headers=HEADERS_RUI
            ).status_code
            == 404
        )

        with db.ligacao() as sql:
            sql(
                "UPDATE notas SET categoria = ? WHERE id = ? AND utilizador = ?",
                ("social", nota["id"], ANA),
            )
        resposta = client.post(
            f"/api/propostas/{proposta['id']}/aprovar", headers=HEADERS_ANA
        )
        assert resposta.status_code == 409
        assert db.listar(ANA)[0]["categoria"] == "social"

        rejeitar = client.post(
            f"/api/propostas/{proposta['id']}/rejeitar", headers=HEADERS_ANA
        )
        assert rejeitar.status_code == 204
        assert (
            client.post(
                f"/api/propostas/{proposta['id']}/aprovar", headers=HEADERS_ANA
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/propostas/nao-existe/aprovar", headers=HEADERS_ANA
            ).status_code
            == 404
        )


def testar_apagar_nota_cancela_proposta_pendente():
    limpar_bd()
    nota = db.criar(ANA, "Nota para apagar", "tarefa")
    proposta = ferramentas.propor_alteracoes_categoria(
        ANA, [{"nota_id": nota["id"], "categoria": "agenda"}]
    )["propostas"][0]
    assert db.apagar(ANA, nota["id"])
    assert db.listar_propostas_categoria(ANA) == []
    with TestClient(app.app) as client:
        resposta = client.post(
            f"/api/propostas/{proposta['id']}/aprovar", headers=HEADERS_ANA
        )
    assert resposta.status_code == 409


def testar_logs_nao_expoem_texto_das_notas_ou_utilizador():
    limpar_bd()
    texto_privado = "segredo-nota-r3-privado"
    nota = db.criar(ANA, texto_privado, "tarefa")
    proposta = ferramentas.propor_alteracoes_categoria(
        ANA, [{"nota_id": nota["id"], "categoria": "agenda"}]
    )["propostas"][0]
    log = io.StringIO()
    handlers_originais = app.logger.handlers[:]
    app.logger.handlers = [logging.StreamHandler(log)]
    try:
        with TestClient(app.app) as client:
            assert (
                client.get("/api/propostas/pendentes", headers=HEADERS_ANA).status_code
                == 200
            )
            assert (
                client.post(
                    f"/api/propostas/{proposta['id']}/aprovar", headers=HEADERS_ANA
                ).status_code
                == 200
            )
        registo = log.getvalue()
        assert texto_privado not in registo
        assert ANA not in registo
    finally:
        app.logger.handlers = handlers_originais


def main():
    testar_proposta_persistida_sem_mudar_notas()
    testar_categorias_invalidas_iguais_e_notas_alheias_descartadas()
    testar_aprovacao_e_rejeicao_individuais_apos_restart()
    testar_isolamento_repeticao_e_proposta_desatualizada()
    testar_apagar_nota_cancela_proposta_pendente()
    testar_logs_nao_expoem_texto_das_notas_ou_utilizador()
    print(
        "OK: propostas sem mutação, validação, isolamento, aprovação/rejeição, "
        "restart e logs privados."
    )


if __name__ == "__main__":
    main()
