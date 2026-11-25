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

        conn = psycopg.connect(url, autocommit=True)
        marcador = "%s"
    else:
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        marcador = "?"
    try:
        cur = conn.cursor()
        cur.execute(ESQUEMA)
        cur.execute(INDICE)
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


def listar(utilizador, categoria=None, procura=None, limite=200):
    query = "SELECT id, utilizador, texto, categoria, criada_em, quando FROM notas WHERE utilizador = ?"
    params = [utilizador]
    if categoria:
        query += " AND categoria = ?"
        params.append(categoria)
    if procura:
        query += " AND LOWER(texto) LIKE ?"
        params.append(f"%{procura.lower()}%")
    query += " ORDER BY criada_em DESC LIMIT ?"
    params.append(limite)
    with ligacao() as sql:
        return [_linha(r) for r in sql(query, params).fetchall()]


def apagar(utilizador, id):
    with ligacao() as sql:
        return (
            sql(
                "DELETE FROM notas WHERE id = ? AND utilizador = ?", (id, utilizador)
            ).rowcount
            > 0
        )
