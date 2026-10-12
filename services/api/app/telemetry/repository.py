"""Escritura de telemetría. Solo INSERT: nada de UPDATE ni DELETE."""
from __future__ import annotations

from typing import Any

from sqlalchemy import insert as generic_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from app.telemetry.orm import TelemetryEventRecord

_TABLE = TelemetryEventRecord.__table__  # type: ignore[attr-defined]


def insert_events(session: Session, rows: list[dict[str, Any]]) -> int:
    """Inserta todas las filas en UNA sola sentencia (multi-VALUES) y una
    transacción. Devuelve cuántas se guardaron realmente: las que ya existían
    (mismo `event_id`) se ignoran con ON CONFLICT DO NOTHING."""
    if not rows:
        return 0
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        statement = pg_insert(_TABLE).values(rows).on_conflict_do_nothing(index_elements=["event_id"])
    elif dialect == "sqlite":
        statement = sqlite_insert(_TABLE).values(rows).on_conflict_do_nothing(index_elements=["event_id"])
    else:  # pragma: no cover - el proyecto solo usa Postgres (y SQLite en tests)
        statement = generic_insert(_TABLE).values(rows)
    stored = len(session.execute(statement.returning(_TABLE.c.id)).all())
    session.commit()
    return stored
