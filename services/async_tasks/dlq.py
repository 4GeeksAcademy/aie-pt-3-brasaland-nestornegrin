"""Dead Letter Queue en base de datos.

Cuando una tarea agota `max_retries`, se registra aquí: `task_id`, número de intento, error y timestamp.
La tabla se crea sola la primera vez (`CREATE TABLE IF NOT EXISTS`); el SQL equivalente, para ejecutarlo a
mano en Supabase, está en `services/api/migrations/004_create_task_dead_letters.sql`.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, MetaData, Table, Text, create_engine, insert, select
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

metadata = MetaData()
task_dead_letters = Table(
    "task_dead_letters",
    metadata,
    # BigInteger en Postgres (BIGSERIAL); Integer en SQLite (los tests), que solo autoincrementa INTEGER.
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column("task_id", Text, nullable=False),
    Column("task_name", Text, nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("error_message", Text, nullable=False),
    Column("failed_at", DateTime(timezone=True), nullable=False),
    Index("ix_task_dead_letters_task_id", "task_id"),
)

_engine: Engine | None = None
_table_ready_for: Engine | None = None
_lock = Lock()


def set_engine(engine: Engine | None) -> None:
    """Inyecta el motor (tests). `None` restablece el comportamiento por defecto (DATABASE_URL)."""
    global _engine, _table_ready_for
    with _lock:
        _engine = engine
        _table_ready_for = None


def get_engine() -> Engine:
    global _engine
    with _lock:
        if _engine is None:
            from dotenv import load_dotenv  # mismo origen de configuración que la API (app/database.py)

            load_dotenv()
            _engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
        return _engine


def ensure_table(engine: Engine) -> None:
    """Crea la tabla si no existe (idempotente) y activa RLS en Postgres, igual que el resto de tablas de `public`."""
    global _table_ready_for
    if _table_ready_for is engine:
        return
    metadata.create_all(engine, checkfirst=True)
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE public.task_dead_letters ENABLE ROW LEVEL SECURITY")
    _table_ready_for = engine


def record_dead_letter(task_id: str, task_name: str, attempt: int, error_message: str) -> None:
    """Registra una tarea muerta. Nunca lanza: si la base de datos falla se deja constancia en el log
    (con el error completo) en lugar de tumbar el manejo del fallo original."""
    try:
        engine = get_engine()
        ensure_table(engine)
        with engine.begin() as connection:
            connection.execute(
                insert(task_dead_letters).values(
                    task_id=task_id,
                    task_name=task_name,
                    attempt=attempt,
                    error_message=error_message,
                    failed_at=datetime.now(timezone.utc),
                )
            )
        logger.error("DLQ: tarea registrada en task_dead_letters task_id=%s attempt=%d", task_id, attempt)
    except Exception:
        logger.exception("DLQ: NO se pudo registrar la tarea task_id=%s attempt=%d en base de datos", task_id, attempt)


def list_dead_letters(limit: int = 50) -> list[dict[str, Any]]:
    """Últimas entradas de la DLQ (más recientes primero)."""
    engine = get_engine()
    ensure_table(engine)
    with engine.connect() as connection:
        rows = connection.execute(
            select(task_dead_letters).order_by(task_dead_letters.c.id.desc()).limit(limit)
        ).mappings()
        return [dict(row) for row in rows]
