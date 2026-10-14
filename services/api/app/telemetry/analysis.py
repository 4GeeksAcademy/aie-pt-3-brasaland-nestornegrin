"""Pipeline de análisis técnico de la telemetría (reporte para ingeniería).

Responde preguntas OPERACIONALES sobre el sistema —volumen, errores, latencia,
autenticación—, no preguntas de negocio (esas se construyen en el hito de Data
Pipelines). Cada métrica es una función independiente que, con los mismos
parámetros, devuelve siempre el mismo resultado y no modifica nada.

Fórmula de cada función (siempre en este orden):

    cargar (SQL) → refinar (Pandas) → convertir tipos → agrupar → agregar → servir

Reglas que se cumplen aquí:
- El filtro de ventana (`start` inclusivo, `end` exclusivo, UTC) y el de
  `event_type` viajan en la consulta SQL: nunca se carga toda la tabla.
- Los campos de `tags` y los flags derivados (`is_error`, `is_failure`) se
  construyen en Pandas, después de cargar.
- `timestamp` llega como texto/naive según el driver: se convierte con
  `pd.to_datetime(..., utc=True)` ANTES de cualquier `groupby` temporal.
- Sin bucles: solo operaciones vectorizadas de Pandas (groupby/agg/count/sum/mean).
- El resultado es una lista de dicts, serializable a JSON tal cual.
- Estas funciones NO resuelven la ventana por defecto: la recibe quien las
  llama (el endpoint la resuelve una sola vez y se la pasa a todas).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import Text, cast, select
from sqlmodel import Session

from app.telemetry.orm import TelemetryEventRecord as Event

# Eventos que cuentan como error TÉCNICO del sistema (catálogo en docs/telemetry/telemetry-plan.md).
# Los rechazos de reglas de negocio (p. ej. `inventory_validation_failed`) y los fallos de
# login no son errores del sistema: el login se mide aparte en `auth_failure_rate`.
ERROR_EVENT_TYPES: tuple[str, ...] = (
    "frontend_error_captured",
    "network_request_failed",
    "api_unhandled_error_raised",
    "request_validation_failed",
)
LATENCY_EVENT_TYPE = "api_latency_recorded"
LOGIN_FAILED = "login_failed"
LOGIN_SUCCEEDED = "login_succeeded"


# --------------------------------------------------------------------------- #
# Piezas compartidas (cargar / refinar / servir)
# --------------------------------------------------------------------------- #
TAGS_COLUMN = cast(Event.tags, Text).label("tags")


def _load(
    session: Session,
    start: datetime,
    end: datetime,
    columns: tuple[Any, ...],
    event_types: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """CARGAR (SQL): solo las columnas y filas que la métrica necesita.

    Rango `[start, end)` y `event_type` se filtran en SQL. `tags` se pide como
    texto para que el resultado sea igual en Postgres (JSONB) y en SQLite (tests).
    """
    statement = select(*columns).where(Event.timestamp >= start, Event.timestamp < end)
    if event_types is not None:
        statement = statement.where(Event.event_type.in_(event_types))
    return pd.read_sql(statement, session.connection())


def _with_tag_fields(frame: pd.DataFrame, fields: tuple[str, ...]) -> pd.DataFrame:
    """REFINAR (Pandas): extrae campos de `tags` como columnas (NaN si el evento no los trae)."""
    parsed = pd.json_normalize(frame["tags"].map(json.loads).tolist()).reindex(columns=list(fields))
    parsed.index = frame.index
    return frame.drop(columns=["tags"]).join(parsed)


def _with_utc_date(frame: pd.DataFrame) -> pd.DataFrame:
    """CONVERTIR TIPOS: timestamp → datetime UTC y día calendario UTC (antes de agrupar)."""
    converted = frame.assign(timestamp=pd.to_datetime(frame["timestamp"], utc=True))
    return converted.assign(date=converted["timestamp"].dt.date)


def _to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """SERVIR: lista de dicts JSON-serializable (las fechas como ISO `YYYY-MM-DD`)."""
    if "date" in frame.columns:
        frame = frame.assign(date=frame["date"].astype(str))
    return frame.reset_index(drop=True).to_dict(orient="records")


# --------------------------------------------------------------------------- #
# Métricas
# --------------------------------------------------------------------------- #
def events_per_day(session: Session, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """¿Cuánto tráfico de telemetría hay cada día y qué lado (frontend/backend/job) lo emite?

    Dimensión: día UTC × `service`. Una caída brusca de un lado indica que dejó de capturarse.
    """
    frame = _load(session, start, end, (Event.timestamp, Event.service))
    frame = _with_utc_date(frame)
    result = frame.groupby(["date", "service"]).size().rename("events").reset_index()
    return _to_records(result)


def event_type_distribution(session: Session, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """¿Qué tipos de evento dominan el tráfico y qué porcentaje del total es cada uno?

    Dimensión: `event_type`. Detecta tipos que inundan (necesitan throttle) o que desaparecen.
    """
    frame = _load(session, start, end, (Event.event_type,))
    counts = frame.groupby("event_type").size().rename("events").reset_index()
    result = counts.assign(share_pct=(counts["events"] / counts["events"].sum() * 100).round(2))
    return _to_records(result.sort_values(["events", "event_type"], ascending=[False, True]))


def error_rate_by_type(session: Session, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """¿Qué errores técnicos ocurren cada día y qué parte del tráfico de ese día representan?

    Dimensión: día UTC × `event_type` de error. `error_rate_pct` = errores de ese tipo ÷ eventos
    totales del día. Se cargan todos los tipos de la ventana (solo 2 columnas) porque la tasa
    necesita el denominador.
    """
    frame = _load(session, start, end, (Event.timestamp, Event.event_type))
    frame = _with_utc_date(frame).assign(is_error=lambda data: data["event_type"].isin(ERROR_EVENT_TYPES))
    daily_total = frame.groupby("date").size().rename("total_events")
    errors = (
        frame[frame["is_error"]].groupby(["date", "event_type"]).size().rename("errors").reset_index()
    )
    result = errors.join(daily_total, on="date")
    result = result.assign(error_rate_pct=(result["errors"] / result["total_events"] * 100).round(2))
    return _to_records(result)


def latency_by_day(session: Session, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """¿Qué tan rápido responde la API cada día y en qué rutas es más lenta?

    Dimensión: día UTC × `routeTemplate`. `samples` cuenta solo las peticiones muestreadas
    (el frontend muestrea el 5 % de las correctas y envía todas las lentas o con error),
    así que sirve para latencias, no para volumen real de peticiones.
    """
    frame = _load(session, start, end, (Event.timestamp, TAGS_COLUMN), event_types=(LATENCY_EVENT_TYPE,))
    frame = _with_tag_fields(frame, ("routeTemplate", "durationMs"))
    frame = _with_utc_date(frame).assign(duration_ms=lambda data: pd.to_numeric(data["durationMs"], errors="coerce"))
    frame = frame.dropna(subset=["routeTemplate", "duration_ms"])
    result = (
        frame.groupby(["date", "routeTemplate"])
        .agg(
            samples=("duration_ms", "count"),
            mean_ms=("duration_ms", "mean"),
            p95_ms=("duration_ms", lambda values: values.quantile(0.95)),
            max_ms=("duration_ms", "max"),
        )
        .round(1)
        .astype({"max_ms": float})  # mismo tipo que mean/p95 en el JSON (400.0, no 400)
        .reset_index()
    )
    return _to_records(result)


def auth_failure_rate(session: Session, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """¿Qué proporción de los intentos de login falla cada día?

    Dimensión: día UTC. `failure_rate_pct` = `login_failed` ÷ (`login_failed` + `login_succeeded`).
    Ambos tipos se cargan en una sola consulta (`event_type IN (...)`) y la razón se calcula en Pandas.
    """
    frame = _load(session, start, end, (Event.timestamp, Event.event_type), event_types=(LOGIN_FAILED, LOGIN_SUCCEEDED))
    frame = _with_utc_date(frame).assign(is_failure=lambda data: data["event_type"] == LOGIN_FAILED)
    result = (
        frame.groupby("date")
        .agg(attempts=("is_failure", "size"), failures=("is_failure", "sum"), failure_rate=("is_failure", "mean"))
        .assign(failure_rate_pct=lambda data: (data["failure_rate"] * 100).round(2))
        .drop(columns=["failure_rate"])
        .reset_index()
    )
    return _to_records(result)


def build_metrics(session: Session, start: datetime, end: datetime) -> dict[str, list[dict[str, Any]]]:
    """Ejecuta todas las métricas sobre la MISMA ventana ya resuelta.

    Las claves son las que aparecen en `metrics` del endpoint. Se enumeran a mano
    (sin bucle) para que añadir o quitar una métrica sea un cambio visible aquí.
    """
    return {
        "events_per_day": events_per_day(session, start, end),
        "event_type_distribution": event_type_distribution(session, start, end),
        "error_rate_by_type": error_rate_by_type(session, start, end),
        "latency_by_day": latency_by_day(session, start, end),
        "auth_failure_rate": auth_failure_rate(session, start, end),
    }
