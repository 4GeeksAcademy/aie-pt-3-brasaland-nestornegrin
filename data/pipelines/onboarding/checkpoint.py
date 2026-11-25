"""Checkpointer del orquestador: es lo que permite que el proceso sobreviva a un reinicio del servicio entre una etapa y la siguiente.
SQLite en archivo por defecto (`ONBOARDING_CHECKPOINT_DB`); PostgreSQL con `ONBOARDING_CHECKPOINT_BACKEND=postgres`
(`ONBOARDING_CHECKPOINT_DB_URL` o `DATABASE_URL`). En memoria SOLO si se pide `:memory:` (desarrollo): se pierde al reiniciar."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from . import config


def build_checkpointer(sqlite_path: str | os.PathLike | None = None):
    if os.environ.get("ONBOARDING_CHECKPOINT_BACKEND", "sqlite").lower() == "postgres" and sqlite_path is None:
        from data.pipelines.rfp_approval.checkpoint import _postgres_saver

        return _postgres_saver(os.environ.get("ONBOARDING_CHECKPOINT_DB_URL") or os.environ["DATABASE_URL"])
    path = str(sqlite_path or os.environ.get("ONBOARDING_CHECKPOINT_DB") or config.DEFAULT_CHECKPOINT_DB)
    if path == ":memory:":
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver()
    from langgraph.checkpoint.sqlite import SqliteSaver

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))
