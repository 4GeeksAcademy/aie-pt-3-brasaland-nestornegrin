"""Sincronización mínima de columnas para las tablas RFP.

`SQLModel.metadata.create_all` crea las tablas que faltan pero NO añade columnas a las que ya existen. La Parte 2 añade columnas
(nullable) a tablas que la Parte 1 pudo haber creado ya en Supabase, así que aquí se añaden las que falten, de forma idempotente.
No es un sistema de migraciones: solo ADD COLUMN de columnas opcionales de las tablas `rfp_*`.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .models import RfpDepartmentSection, RfpMetadata, RfpTicket

logger = logging.getLogger(__name__)


def ensure_columns(engine: Engine) -> list[str]:
    """Devuelve las columnas añadidas («tabla.columna»)."""
    added: list[str] = []
    inspector = inspect(engine)
    quote = engine.dialect.identifier_preparer.quote
    for model in (RfpTicket, RfpMetadata, RfpDepartmentSection):
        table = model.__table__
        if not inspector.has_table(table.name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            ddl = f"ALTER TABLE {quote(table.name)} ADD COLUMN {quote(column.name)} {column.type.compile(dialect=engine.dialect)}"
            with engine.begin() as conn:
                conn.execute(text(ddl))
            added.append(f"{table.name}.{column.name}")
            logger.info("rfp: columna añadida %s.%s", table.name, column.name)
    return added
