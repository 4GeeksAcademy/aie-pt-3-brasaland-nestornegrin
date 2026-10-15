"""Consultas de EXTRACCIÓN del pipeline (diseño §3.1). Todas son de solo lectura.

`public.telemetry_events` y las tablas de inventario no se modifican jamás desde el pipeline. Cada función
recibe una conexión SQLAlchemy y devuelve un DataFrame con las columnas que `data/process/business_kpis.py` espera.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

import pandas as pd
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from data.process.business_kpis import KPI_EVENT_TYPES

_EVENT_COLUMNS = 'id, event_id::text AS event_id, event_type, service, "timestamp", tags'
EVENT_COLUMNS = ["id", "event_id", "event_type", "service", "timestamp", "tags"]


def fetch_max_event_id(connection: Connection) -> int:
    """Tope superior congelado al inicio de la corrida: todo lo que se lea cumple `id <= tope`."""
    return int(connection.execute(text("SELECT COALESCE(MAX(id), 0) FROM public.telemetry_events")).scalar_one())


def fetch_events_since(connection: Connection, from_id: int, to_id: int, page_size: int) -> pd.DataFrame:
    """Eventos obligatorios con `from_id < id <= to_id`, en páginas por clave (`id > último`), sin OFFSET."""
    statement = text(
        f"SELECT {_EVENT_COLUMNS} FROM public.telemetry_events "
        "WHERE id > :last AND id <= :to_id AND event_type IN :types ORDER BY id LIMIT :page_size"
    ).bindparams(bindparam("types", expanding=True))
    pages: list[pd.DataFrame] = []
    last = from_id
    while True:
        page = pd.read_sql(statement, connection, params={"last": last, "to_id": to_id, "types": list(KPI_EVENT_TYPES), "page_size": page_size})
        if page.empty:
            break
        pages.append(page)
        last = int(page["id"].iloc[-1])
        if len(page) < page_size:
            break
    return pd.concat(pages, ignore_index=True) if pages else pd.DataFrame(columns=EVENT_COLUMNS)


def fetch_events_in_range(connection: Connection, ts_from: datetime, ts_to: datetime, to_id: int) -> pd.DataFrame:
    """Eventos obligatorios con `ts_from <= timestamp < ts_to` y `id <= to_id` (recalcular un cubo ENTERO)."""
    statement = text(
        f'SELECT {_EVENT_COLUMNS} FROM public.telemetry_events WHERE "timestamp" >= :ts_from AND "timestamp" < :ts_to '
        "AND id <= :to_id AND event_type IN :types ORDER BY id"
    ).bindparams(bindparam("types", expanding=True))
    frame = pd.read_sql(statement, connection, params={"ts_from": ts_from, "ts_to": ts_to, "to_id": to_id, "types": list(KPI_EVENT_TYPES)})
    return frame if not frame.empty else pd.DataFrame(columns=EVENT_COLUMNS)


def fetch_dim_restaurant(connection: Connection) -> pd.DataFrame:
    return pd.read_sql(text("SELECT restaurant, country, city, timezone FROM reporting.dim_restaurant ORDER BY restaurant"), connection)


def fetch_exits(connection: Connection, restaurants: Iterable[str], ts_from: datetime, ts_to: datetime, exit_ids: Iterable[int]) -> pd.DataFrame:
    """`ingredient_exits` del dominio: las del rango (cobertura) y las referidas por los eventos (razón de merma)."""
    statement = text(
        "SELECT x.id AS exit_id, x.ingredient_id, x.quantity, x.reason, x.created_at, i.restaurant "
        "FROM public.ingredient_exits x JOIN public.ingredients i ON i.id = x.ingredient_id "
        "WHERE (i.restaurant IN :restaurants AND x.created_at >= :ts_from AND x.created_at < :ts_to) OR x.id IN :exit_ids"
    ).bindparams(bindparam("restaurants", expanding=True), bindparam("exit_ids", expanding=True))
    ids = [int(value) for value in exit_ids] or [-1]  # IN () vacío no es SQL válido
    frame = pd.read_sql(statement, connection, params={"restaurants": list(restaurants) or [""], "ts_from": ts_from, "ts_to": ts_to, "exit_ids": ids})
    # `created_at` puede ser `timestamp without time zone` (naive, en UTC): se normaliza igual que en `fetch_stock_movements`.
    return frame.assign(created_at=pd.to_datetime(frame["created_at"], utc=True)) if not frame.empty else frame


def fetch_stock_movements(connection: Connection, restaurants: Iterable[str], ts_to: datetime) -> pd.DataFrame:
    """Entradas (+) y salidas (−) de stock anteriores a `ts_to`: base del stock al cierre (K6)."""
    statement = text(
        "SELECT i.id AS ingredient_id, i.restaurant, e.created_at AS ts, e.quantity AS delta "
        "FROM public.ingredient_entries e JOIN public.ingredients i ON i.id = e.ingredient_id "
        "WHERE i.restaurant IN :restaurants AND e.created_at < :ts_to "
        "UNION ALL "
        "SELECT i.id, i.restaurant, x.created_at, -x.quantity "
        "FROM public.ingredient_exits x JOIN public.ingredients i ON i.id = x.ingredient_id "
        "WHERE i.restaurant IN :restaurants AND x.created_at < :ts_to"
    ).bindparams(bindparam("restaurants", expanding=True))
    frame = pd.read_sql(statement, connection, params={"restaurants": list(restaurants) or [""], "ts_to": ts_to})
    return frame.assign(ts=pd.to_datetime(frame["ts"], utc=True)) if not frame.empty else frame.assign(ts=pd.Series(dtype="datetime64[ns, UTC]"))


def fetch_domain_fingerprint(connection: Connection) -> dict[str, Any]:
    """Huella barata del estado del dominio: forma parte de la clave de caché de la transformación."""
    row = connection.execute(
        text(
            "SELECT (SELECT COUNT(*) FROM public.ingredient_exits), (SELECT COALESCE(MAX(id), 0) FROM public.ingredient_exits), "
            "(SELECT COUNT(*) FROM public.ingredient_entries), (SELECT COALESCE(MAX(id), 0) FROM public.ingredient_entries)"
        )
    ).one()
    return {"exits_count": int(row[0]), "exits_max_id": int(row[1]), "entries_count": int(row[2]), "entries_max_id": int(row[3])}
