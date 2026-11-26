"""Notas guardadas no servidor. Postgres em produção (DATABASE_URL), SQLite em local e nos testes.

Porquê assim: ver BASE_DE_DADOS.md.
"""

import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SQLITE_PATH = Path(
    os.environ.get("NOTAS_SQLITE", Path(__file__).resolve().parent / "notas.db")
)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS notas (
    id TEXT PRIMARY KEY,
    utilizador TEXT NOT NULL,
    texto TEXT NOT NULL,
    categoria TEXT NOT NULL,
    criada_em TEXT NOT NULL,
    quando TEXT
)"""
INDICE = "CREATE INDEX IF NOT EXISTS notas_utilizador ON notas (utilizador, criada_em)"
ESQUEMA_PROPOSTAS = """
CREATE TABLE IF NOT EXISTS propostas_categoria (
    id TEXT PRIMARY KEY,
    lote_id TEXT NOT NULL,
    utilizador TEXT NOT NULL,
    nota_id TEXT NOT NULL,
    categoria_atual TEXT NOT NULL,
    categoria_proposta TEXT NOT NULL,
    estado TEXT NOT NULL CHECK (estado IN ('pendente', 'aprovada', 'rejeitada', 'cancelada')),
    criada_em TEXT NOT NULL,
    resolvida_em TEXT,
    UNIQUE (lote_id, nota_id)
)"""
INDICE_PROPOSTAS = (
    "CREATE INDEX IF NOT EXISTS propostas_utilizador_estado "
    "ON propostas_categoria (utilizador, estado, criada_em)"
)
ESQUEMA_RESUMOS_DIARIOS = """
CREATE TABLE IF NOT EXISTS resumos_diarios (
    id TEXT PRIMARY KEY,
    utilizador TEXT NOT NULL,
    dia TEXT NOT NULL,
    resumo TEXT NOT NULL,
    total_notas INTEGER NOT NULL,
    criada_em TEXT NOT NULL,
    UNIQUE (utilizador, dia)
)"""
INDICE_RESUMOS_DIARIOS = (
    "CREATE INDEX IF NOT EXISTS resumos_diarios_utilizador_dia "
    "ON resumos_diarios (utilizador, dia DESC)"
)

ESQUEMA_CATEGORIAS = """
CREATE TABLE IF NOT EXISTS categorias_personalizadas (
    id TEXT PRIMARY KEY,
    utilizador TEXT NOT NULL,
    nome TEXT NOT NULL,
    chave TEXT NOT NULL,
    estado TEXT NOT NULL CHECK (estado IN ('pendente', 'aprovada')),
    criada_em TEXT NOT NULL,
    UNIQUE (utilizador, chave)
)"""
INDICE_CATEGORIAS = """
CREATE INDEX IF NOT EXISTS categorias_por_utilizador
ON categorias_personalizadas (utilizador, estado)
"""


def url_postgres():
    # A integração Neon do Vercel cria DATABASE_URL (e outras POSTGRES_*); aceitamos as duas.
    return os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")


@contextmanager
def ligacao():
    """Uma ligação por pedido: em serverless não há processo que fique vivo entre pedidos."""
    url = url_postgres()
    conn: Any
    marcador: str
    if url:
        import psycopg

        conn = psycopg.connect(url)
        marcador = "%s"
    else:
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        marcador = "?"
    try:
        cur = conn.cursor()
        cur.execute(ESQUEMA)
        cur.execute(INDICE)
        cur.execute(ESQUEMA_PROPOSTAS)
        cur.execute(INDICE_PROPOSTAS)
        cur.execute(ESQUEMA_RESUMOS_DIARIOS)
        cur.execute(INDICE_RESUMOS_DIARIOS)

        cur.execute(ESQUEMA_CATEGORIAS)
        cur.execute(INDICE_CATEGORIAS)
        if url:
            cur.execute("ALTER TABLE notas ADD COLUMN IF NOT EXISTS quando TEXT")
        else:
            # A tabela pode ser anterior a R2.2. Bloquear e voltar a verificar
            # evita que dois pedidos SQLite tentem migrar ao mesmo tempo.
            colunas = {row[1] for row in cur.execute("PRAGMA table_info(notas)")}
            if "quando" not in colunas:
                cur.execute("BEGIN IMMEDIATE")
                colunas = {row[1] for row in cur.execute("PRAGMA table_info(notas)")}
                if "quando" not in colunas:
                    cur.execute("ALTER TABLE notas ADD COLUMN quando TEXT")

        def sql(query, params=()):
            cur.execute(query.replace("?", marcador), params)
            return cur

        yield sql
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _linha(row):
    keys = ("id", "utilizador", "texto", "categoria", "criada_em", "quando")
    return (
        dict(zip(keys, row))
        if not isinstance(row, sqlite3.Row)
        else {k: row[k] for k in keys}
    )


def criar(utilizador, texto, categoria, criada_em=None, id=None, quando=None):
    nota = {
        "id": id or str(uuid.uuid4()),
        "utilizador": utilizador,
        "texto": texto,
        "categoria": categoria,
        "criada_em": criada_em or datetime.now(timezone.utc).isoformat(),
        "quando": quando,
    }
    with ligacao() as sql:
        sql(
            "INSERT INTO notas (id, utilizador, texto, categoria, criada_em, quando) VALUES (?, ?, ?, ?, ?, ?)",
            (
                nota["id"],
                nota["utilizador"],
                nota["texto"],
                nota["categoria"],
                nota["criada_em"],
                nota["quando"],
            ),
        )
    return nota


def listar(
    utilizador, categoria=None, procura=None, limite=200, desde=None, antes_de=None
):
    """desde (inclusivo) e antes_de (exclusivo) são datas ISO; criada_em é texto ISO em UTC,
    por isso a comparação de texto respeita a ordem cronológica."""
    query = "SELECT id, utilizador, texto, categoria, criada_em, quando FROM notas WHERE utilizador = ?"
    params = [utilizador]
    if categoria:
        query += " AND categoria = ?"
        params.append(categoria)
    if procura:
        query += " AND LOWER(texto) LIKE ?"
        params.append(f"%{procura.lower()}%")
    if desde:
        query += " AND criada_em >= ?"
        params.append(desde)
    if antes_de:
        query += " AND criada_em < ?"
        params.append(antes_de)
    query += " ORDER BY criada_em DESC LIMIT ?"
    params.append(limite)
    with ligacao() as sql:
        return [_linha(r) for r in sql(query, params).fetchall()]


def apagar(utilizador, id):
    with ligacao() as sql:
        apagadas = sql(
            "DELETE FROM notas WHERE id = ? AND utilizador = ?", (id, utilizador)
        ).rowcount
        if apagadas:
            sql(
                "UPDATE propostas_categoria SET estado = 'cancelada', resolvida_em = ? "
                "WHERE utilizador = ? AND nota_id = ? AND estado = 'pendente'",
                (datetime.now(timezone.utc).isoformat(), utilizador, id),
            )
        return apagadas > 0


def criar_propostas_categoria(utilizador, propostas, categorias):
    """Guarda só propostas válidas e diferentes da categoria atual da nota."""
    if not isinstance(propostas, list):
        return []

    candidatos = []
    vistos = set()
    for proposta in propostas[:50]:
        if not isinstance(proposta, dict) or set(proposta) != {"nota_id", "categoria"}:
            continue
        nota_id, categoria = proposta["nota_id"], proposta["categoria"]
        if (
            not isinstance(nota_id, str)
            or not nota_id
            or len(nota_id) > 200
            or not isinstance(categoria, str)
            or categoria not in categorias
            or nota_id in vistos
        ):
            continue
        vistos.add(nota_id)
        candidatos.append((nota_id, categoria))

    if not candidatos:
        return []

    lote_id = str(uuid.uuid4())
    agora = datetime.now(timezone.utc).isoformat()
    guardadas = []
    with ligacao() as sql:
        for nota_id, categoria in candidatos:
            proposta_existente = sql(
                "SELECT 1 FROM propostas_categoria "
                "WHERE utilizador = ? AND nota_id = ? AND estado = 'pendente'",
                (utilizador, nota_id),
            ).fetchone()
            if proposta_existente:
                continue
            nota = sql(
                "SELECT id, texto, categoria FROM notas "
                "WHERE id = ? AND utilizador = ?",
                (nota_id, utilizador),
            ).fetchone()
            if not nota:
                continue
            linha = (
                dict(nota)
                if isinstance(nota, sqlite3.Row)
                else {
                    "id": nota[0],
                    "texto": nota[1],
                    "categoria": nota[2],
                }
            )
            if linha["categoria"] == categoria:
                continue
            proposta_id = str(uuid.uuid4())
            sql(
                "INSERT INTO propostas_categoria "
                "(id, lote_id, utilizador, nota_id, categoria_atual, categoria_proposta, "
                "estado, criada_em, resolvida_em) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pendente', ?, NULL)",
                (
                    proposta_id,
                    lote_id,
                    utilizador,
                    nota_id,
                    linha["categoria"],
                    categoria,
                    agora,
                ),
            )
            guardadas.append(
                {
                    "id": proposta_id,
                    "lote_id": lote_id,
                    "nota_id": nota_id,
                    "texto": linha["texto"],
                    "categoria_atual": linha["categoria"],
                    "categoria_proposta": categoria,
                    "estado": "pendente",
                    "criada_em": agora,
                }
            )
    return guardadas


def listar_propostas_categoria(utilizador, estado="pendente", lote_id=None):
    if estado not in {"pendente", "aprovada", "rejeitada", "cancelada"}:
        raise ValueError("Estado de proposta inválido.")
    query = (
        "SELECT p.id, p.lote_id, p.nota_id, n.texto, p.categoria_atual, "
        "p.categoria_proposta, p.estado, p.criada_em "
        "FROM propostas_categoria p JOIN notas n "
        "ON n.id = p.nota_id AND n.utilizador = p.utilizador "
        "WHERE p.utilizador = ? AND p.estado = ?"
    )
    params = [utilizador, estado]
    if lote_id is not None:
        query += " AND p.lote_id = ?"
        params.append(lote_id)
    query += " ORDER BY p.criada_em, p.id LIMIT ?"
    params.append(200)
    with ligacao() as sql:
        rows = sql(query, params).fetchall()
    keys = (
        "id",
        "lote_id",
        "nota_id",
        "texto",
        "categoria_atual",
        "categoria_proposta",
        "estado",
        "criada_em",
    )
    return [
        dict(zip(keys, row))
        if not isinstance(row, sqlite3.Row)
        else {key: row[key] for key in keys}
        for row in rows
    ]


class PropostaDesatualizada(Exception):
    """A nota mudou ou foi apagada desde que a proposta foi criada."""


def aprovar_proposta_categoria(utilizador, proposta_id):
    agora = datetime.now(timezone.utc).isoformat()
    with ligacao() as sql:
        proposta = sql(
            "SELECT nota_id, categoria_atual, categoria_proposta, estado "
            "FROM propostas_categoria WHERE id = ? AND utilizador = ?",
            (proposta_id, utilizador),
        ).fetchone()
        if not proposta:
            return "nao_encontrada"
        if isinstance(proposta, sqlite3.Row):
            nota_id = proposta["nota_id"]
            categoria_atual = proposta["categoria_atual"]
            categoria_proposta = proposta["categoria_proposta"]
            estado = proposta["estado"]
        else:
            nota_id, categoria_atual, categoria_proposta, estado = proposta
        if estado != "pendente":
            return "ja_resolvida"

        atualizada = sql(
            "UPDATE propostas_categoria SET estado = 'aprovada', resolvida_em = ? "
            "WHERE id = ? AND utilizador = ? AND estado = 'pendente'",
            (agora, proposta_id, utilizador),
        )
        if atualizada.rowcount != 1:
            return "ja_resolvida"

        nota_atualizada = sql(
            "UPDATE notas SET categoria = ? "
            "WHERE id = ? AND utilizador = ? AND categoria = ?",
            (categoria_proposta, nota_id, utilizador, categoria_atual),
        )
        if nota_atualizada.rowcount != 1:
            raise PropostaDesatualizada
    return {"nota_id": nota_id, "categoria": categoria_proposta}


def rejeitar_proposta_categoria(utilizador, proposta_id):
    agora = datetime.now(timezone.utc).isoformat()
    with ligacao() as sql:
        proposta = sql(
            "SELECT estado FROM propostas_categoria WHERE id = ? AND utilizador = ?",
            (proposta_id, utilizador),
        ).fetchone()
        if not proposta:
            return "nao_encontrada"
        estado = (
            proposta["estado"] if isinstance(proposta, sqlite3.Row) else proposta[0]
        )
        if estado != "pendente":
            return "ja_resolvida"
        atualizada = sql(
            "UPDATE propostas_categoria SET estado = 'rejeitada', resolvida_em = ? "
            "WHERE id = ? AND utilizador = ? AND estado = 'pendente'",
            (agora, proposta_id, utilizador),
        )
        return "rejeitada" if atualizada.rowcount == 1 else "ja_resolvida"


def utilizadores_com_notas(desde, antes_de):
    with ligacao() as sql:
        rows = sql(
            "SELECT DISTINCT utilizador FROM notas "
            "WHERE criada_em >= ? AND criada_em < ? ORDER BY utilizador",
            (desde, antes_de),
        ).fetchall()
    return [
        row["utilizador"] if isinstance(row, sqlite3.Row) else row[0] for row in rows
    ]


def resumo_diario_existe(utilizador, dia):
    with ligacao() as sql:
        return (
            sql(
                "SELECT 1 FROM resumos_diarios WHERE utilizador = ? AND dia = ?",
                (utilizador, dia),
            ).fetchone()
            is not None
        )


def guardar_resumo_diario(utilizador, dia, resumo, total_notas):
    with ligacao() as sql:
        inserido = sql(
            "INSERT INTO resumos_diarios "
            "(id, utilizador, dia, resumo, total_notas, criada_em) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (utilizador, dia) DO NOTHING",
            (
                str(uuid.uuid4()),
                utilizador,
                dia,
                resumo,
                total_notas,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return inserido.rowcount == 1


def obter_resumo_diario(utilizador):
    with ligacao() as sql:
        row = sql(
            "SELECT dia, resumo, total_notas, criada_em FROM resumos_diarios "
            "WHERE utilizador = ? ORDER BY dia DESC LIMIT 1",
            (utilizador,),
        ).fetchone()
    if not row:
        return None
    keys = ("dia", "resumo", "total_notas", "criada_em")
    return (
        {key: row[key] for key in keys}
        if isinstance(row, sqlite3.Row)
        else dict(zip(keys, row))
    )


def propor_categoria(utilizador: str, nome: str, chave: str) -> str | None:
    identificador = str(uuid.uuid4())
    with ligacao() as sql:
        inserida = sql(
            """INSERT INTO categorias_personalizadas
            (id, utilizador, nome, chave, estado, criada_em)
            VALUES (?, ?, ?, ?, 'pendente', ?)
            ON CONFLICT (utilizador, chave) DO NOTHING RETURNING id""",
            (
                identificador,
                utilizador,
                nome,
                chave,
                datetime.now(timezone.utc).isoformat(),
            ),
        ).fetchone()
    return str(inserida[0]) if inserida else None


def categorias_aprovadas(utilizador: str) -> list[str]:
    with ligacao() as sql:
        linhas = sql(
            """SELECT nome FROM categorias_personalizadas
            WHERE utilizador = ? AND estado = 'aprovada' ORDER BY nome""",
            (utilizador,),
        ).fetchall()
    return [str(linha[0]) for linha in linhas]


def categorias_pendentes(utilizador: str) -> list[dict[str, str]]:
    with ligacao() as sql:
        linhas = sql(
            """SELECT id, nome FROM categorias_personalizadas
            WHERE utilizador = ? AND estado = 'pendente' ORDER BY criada_em""",
            (utilizador,),
        ).fetchall()
    return [
        {"id": str(linha[0]), "tipo": "criar_categoria", "nome": str(linha[1])}
        for linha in linhas
    ]


def decidir_categoria(utilizador: str, identificador: str, aprovar: bool) -> str | None:
    with ligacao() as sql:
        if aprovar:
            alterada = sql(
                """UPDATE categorias_personalizadas SET estado = 'aprovada'
                WHERE id = ? AND utilizador = ? AND estado = 'pendente'
                RETURNING nome""",
                (identificador, utilizador),
            ).fetchone()
        else:
            alterada = sql(
                """DELETE FROM categorias_personalizadas
                WHERE id = ? AND utilizador = ? AND estado = 'pendente'
                RETURNING nome""",
                (identificador, utilizador),
            ).fetchone()
    return str(alterada[0]) if alterada else None
