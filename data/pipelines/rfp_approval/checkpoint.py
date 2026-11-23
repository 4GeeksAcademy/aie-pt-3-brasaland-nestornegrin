"""Checkpointer del flujo de aprobación. Sin checkpoint no hay `interrupt`: es lo que permite pausar y reanudar EXACTAMENTE donde se quedó.

Prioridad: PostgreSQL (`RFP_CHECKPOINT_BACKEND=postgres`, usa `RFP_CHECKPOINT_DB_URL` o `DATABASE_URL`) → SQLite en archivo
(`RFP_CHECKPOINT_DB`, por defecto `data/runtime/rfp_checkpoints.sqlite`). En memoria SOLO si se pide explícitamente
(`RFP_CHECKPOINT_DB=:memory:`) y para desarrollo local: se pierde al reiniciar el proceso.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_SQLITE = Path(__file__).resolve().parents[3] / "data" / "runtime" / "rfp_checkpoints.sqlite"


def build_checkpointer(sqlite_path: str | os.PathLike | None = None):
    backend = os.environ.get("RFP_CHECKPOINT_BACKEND", "sqlite").lower()
    if backend == "postgres" and sqlite_path is None:
        return _postgres_saver(os.environ.get("RFP_CHECKPOINT_DB_URL") or os.environ["DATABASE_URL"])
    path = str(sqlite_path or os.environ.get("RFP_CHECKPOINT_DB") or DEFAULT_SQLITE)
    if path == ":memory:":
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver()
    from langgraph.checkpoint.sqlite import SqliteSaver

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))


def _postgres_saver(url: str):
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg import Connection
    from psycopg.rows import dict_row

    # autocommit + dict_row son obligatorios para el saver; prepare_threshold=None evita errores con el pooler de Supabase.
    connection = Connection.connect(url, autocommit=True, prepare_threshold=None, row_factory=dict_row)
    saver = PostgresSaver(connection)
    saver.setup()  # crea las tablas de checkpoint si no existen (idempotente)
    return saver
