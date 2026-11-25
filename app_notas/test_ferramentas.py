"""R2.4a: listar_notas e procurar_notas. Corre em SQLite, sem rede nem chaves: python test_ferramentas.py"""

import os
import tempfile
import uuid

os.environ["NOTAS_SQLITE"] = os.path.join(tempfile.mkdtemp(), "teste.db")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

import db
from ferramentas import ErroFerramenta, listar_notas, procurar_notas


def textos(notas):
    return [n["texto"] for n in notas]


def falha(funcao, *args, **kwargs):
    try:
        funcao(*args, **kwargs)
    except ErroFerramenta:
        return True
    return False


def main():
    ana, rui, novo = (str(uuid.uuid4()) for _ in range(3))
    db.criar(ana, "Ligar à Sofia sobre o jantar", "tarefa", "2026-11-10T09:00:00+00:00")
    db.criar(ana, "Comprar pão", "tarefa", "2026-11-20T23:30:00+00:00")
    db.criar(ana, "App para relógios", "ideia", "2026-11-21T08:00:00+00:00")
    db.criar(rui, "Almoço com a Sofia", "social", "2026-11-20T12:00:00+00:00")
    db.criar(rui, "Entregar relatório", "tarefa", "2026-11-20T15:00:00+00:00")

    # listar_notas: todas, das mais recentes para as mais antigas, sem o id do utilizador.
    todas = listar_notas(ana)
    assert textos(todas) == [
        "App para relógios",
        "Comprar pão",
        "Ligar à Sofia sobre o jantar",
    ]
    assert all(set(n) == {"id", "texto", "categoria", "criada_em"} for n in todas)

    # Filtro por categoria: só tarefas, nenhuma nota de outra categoria.
    tarefas = listar_notas(ana, categoria="tarefa")
    assert textos(tarefas) == ["Comprar pão", "Ligar à Sofia sobre o jantar"]
    assert {n["categoria"] for n in tarefas} == {"tarefa"}

    # Intervalo de datas: dias inteiros, com os dois extremos incluídos.
    assert textos(listar_notas(ana, ate="2026-11-20")) == [
        "Comprar pão",
        "Ligar à Sofia sobre o jantar",
    ], "ate inclui o próprio dia até às 23:59"
    assert textos(listar_notas(ana, desde="2026-11-21")) == ["App para relógios"]
    assert textos(listar_notas(ana, desde="2026-11-20", ate="2026-11-20")) == [
        "Comprar pão"
    ]
    assert listar_notas(ana, desde="2026-12-01") == []

    # procurar_notas: texto sem distinguir maiúsculas, combinável com os filtros.
    assert textos(procurar_notas(ana, "SOFIA")) == ["Ligar à Sofia sobre o jantar"]
    assert textos(procurar_notas(ana, "  sofia  ", categoria="tarefa")) == [
        "Ligar à Sofia sobre o jantar"
    ]
    assert procurar_notas(ana, "sofia", desde="2026-11-15") == []
    assert procurar_notas(ana, "sofia", categoria="ideia") == []

    # Isolamento: as mesmas perguntas, feitas por outra pessoa, não devolvem notas da Ana.
    ids_ana = {n["id"] for n in todas}
    assert textos(procurar_notas(rui, "sofia")) == ["Almoço com a Sofia"]
    assert textos(listar_notas(rui, categoria="tarefa")) == ["Entregar relatório"]
    for utilizador in (rui, novo):
        respostas = [
            listar_notas(utilizador),
            listar_notas(utilizador, categoria="tarefa"),
            listar_notas(utilizador, desde="2026-11-01", ate="2026-11-30"),
            procurar_notas(utilizador, "sofia"),
            procurar_notas(utilizador, "pão"),
        ]
        vistos = {n["id"] for notas in respostas for n in notas}
        assert not vistos & ids_ana, "ninguém vê notas da Ana"
    assert listar_notas(novo) == [] and procurar_notas(novo, "sofia") == []

    # Argumentos inválidos: erro claro, em vez de devolver notas por engano.
    assert falha(listar_notas, ""), "sem utilizador não há consulta"
    assert falha(procurar_notas, "   ", "sofia")
    assert falha(listar_notas, ana, categoria="tarefas"), "categoria desconhecida"
    assert falha(listar_notas, ana, desde="ontem"), "data inválida"
    assert falha(listar_notas, ana, desde="2026-11-21", ate="2026-11-20")
    assert falha(procurar_notas, ana, "  "), "texto vazio"

    print(
        "OK: listar_notas e procurar_notas (categoria, texto, datas), isolamento e erros."
    )


if __name__ == "__main__":
    main()
