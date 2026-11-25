"""Persistência dos checkpoints do agente."""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver

import db


@contextmanager
def abrir_checkpointer() -> Iterator[BaseCheckpointSaver]:
    url = db.url_postgres()
    if url:
        from langgraph.checkpoint.postgres import PostgresSaver

        with PostgresSaver.from_conn_string(url) as saver:
            saver.setup()
            yield saver
    else:
        if os.environ.get("VERCEL") == "1":
            raise RuntimeError(
                "Configura DATABASE_URL ou POSTGRES_URL para persistir a memória na Vercel."
            )
        with SqliteSaver.from_conn_string(str(db.SQLITE_PATH)) as saver:
            saver.setup()
            yield saver


def criar_thread_id(utilizador: str, conversa: str) -> str:
    identidade = json.dumps(
        [utilizador, conversa], ensure_ascii=False, separators=(",", ":")
    )
    return sha256(identidade.encode("utf-8")).hexdigest()
