"""Funciones que expone el pipeline a la aplicación (`services/reporting/` las IMPORTA; diseño §9.1 y §9.3).

Regla de diseño: la lógica del pipeline vive en `data/`; los handlers HTTP de `services/reporting/` solo
validan la petición y llaman a estas tres funciones. Este módulo NO importa nada de `services/`: el `engine`
lo recibe como argumento (la API le pasa el suyo).

    get_pipeline_status(engine)                         → GET  /reporting/inventory-performance/status
    trigger_inventory_performance_run(engine, …)        → POST /reporting/inventory-performance/runs
    query_inventory_kpis(engine, filters)               → GET  /reporting/inventory-performance/kpis

`query_inventory_kpis` solo lee `reporting.*` (nunca `telemetry_events` ni `GET /telemetry/report`).
Prefect se importa de forma perezosa en el disparo manual: consultar estado o KPIs no carga el motor de flows.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from data.pipelines.inventory_performance import db, settings
from data.pipelines.inventory_performance.windows import resolve_window
from data.process import business_kpis as kpi

logger = logging.getLogger(__name__)

DEFAULT_KPI_DAYS = 14
GRANULARITIES = ("day", "week")
# Columnas que el dashboard consume. K1–K6 → outbound_orders, units_issued, spoilage_rate_pct, stock_alerts_*,
# validation_rejection_rate_pct, ingredients_*_eod (ver tabla de §2.3 del documento de diseño).
KPI_ITEM_COLUMNS = [
    "report_date", "restaurant", "country", "outbound_orders", "units_issued", "spoilage_units", "spoilage_rate_pct",
    "stock_alerts_low", "stock_alerts_critical", "validation_failures", "validation_rejection_rate_pct",
    "ingredients_at_risk_eod", "ingredients_critical_eod", "telemetry_coverage_pct", "events_deduplicated",
    "capture_health", "revision",
]


class PipelineAlreadyRunning(RuntimeError):
    """Ya hay una corrida activa: el endpoint responde 409 con su `run_id`."""

    def __init__(self, run_id: str):
        super().__init__(f"ya hay una corrida activa ({run_id})")
        self.run_id = run_id


class InvalidKpiFilters(ValueError):
    """Filtros de consulta inválidos: el endpoint responde 400."""


@dataclass(frozen=True)
class KpiFilters:
    date_from: date | None = None
    date_to: date | None = None
    restaurant: str | None = None
    country: str | None = None
    granularity: str = "day"


def _iso(value: Any) -> Any:
    """Fechas → ISO 8601; el resto, tal cual (los UUID a texto)."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return str(value) if value.__class__.__name__ == "UUID" else value


def _plain(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _iso(value) for key, value in row.items()}


# --------------------------------------------------------------------------- #
# 1 · Estado y metadata de la última corrida
# --------------------------------------------------------------------------- #
def get_pipeline_status(engine: Engine) -> dict[str, Any]:
    """Última corrida, última exitosa, retraso del checkpoint, si hay una activa y la salud de captura reciente."""
    db.ensure_reporting_schema(engine)
    with engine.connect() as connection:
        last_run = connection.execute(
            text(
                "SELECT run_id, trigger, triggered_by, status, started_at, finished_at, rows_extracted, rows_deduplicated, "
                "rows_rejected, buckets_recomputed, rows_inserted, rows_updated, watermark_from, watermark_to, errors, "
                "window_from, window_to, code_version FROM reporting.pipeline_runs WHERE pipeline_name = :name "
                "ORDER BY started_at DESC LIMIT 1"
            ),
            {"name": settings.PIPELINE_NAME},
        ).mappings().first()
        last_success_at = connection.execute(
            text("SELECT MAX(finished_at) FROM reporting.pipeline_runs WHERE pipeline_name = :name AND status = 'completed'"),
            {"name": settings.PIPELINE_NAME},
        ).scalar()
        active = connection.execute(
            text(
                "SELECT run_id FROM reporting.pipeline_runs WHERE pipeline_name = :name AND status = 'running' "
                "AND heartbeat_at > now() - make_interval(secs => :timeout) ORDER BY started_at DESC LIMIT 1"
            ),
            {"name": settings.PIPELINE_NAME, "timeout": settings.HEARTBEAT_TIMEOUT.total_seconds()},
        ).scalar()
        watermark = connection.execute(
            text("SELECT last_event_id FROM reporting.pipeline_watermarks WHERE pipeline_name = :name"), {"name": settings.PIPELINE_NAME}
        ).scalar() or 0
        newest_event = connection.execute(text("SELECT COALESCE(MAX(id), 0) FROM public.telemetry_events")).scalar_one()
        health = connection.execute(
            text(
                "SELECT capture_health, COUNT(*) AS buckets FROM reporting.restaurant_inventory_daily "
                "WHERE report_date >= CURRENT_DATE - :days GROUP BY capture_health"
            ),
            {"days": settings.LOOKBACK_DAYS},
        ).all()
    stale = last_success_at is None or datetime.now(timezone.utc) - last_success_at > settings.STALE_AFTER
    return {
        "last_run": _plain(dict(last_run)) if last_run else None,
        "last_success_at": _iso(last_success_at) if last_success_at else None,
        "watermark_lag": max(int(newest_event) - int(watermark), 0),  # eventos de telemetría aún no procesados
        "is_running": active is not None,
        "active_run_id": str(active) if active else None,
        "is_stale": bool(stale),  # el cron no corrió: hace más de 26 h (diseño §10.4)
        "capture_health": {name: int(count) for name, count in health},
    }


# --------------------------------------------------------------------------- #
# 2 · Disparo manual
# --------------------------------------------------------------------------- #
def _launch_flow(run_id: str, triggered_by: int | None, window: tuple[date, date] | None) -> None:
    """Ejecuta el flow en un hilo aparte: el endpoint responde 202 sin esperar al ETL."""

    def _run() -> None:
        try:
            from data.pipelines.pipeline import inventory_performance_daily_flow  # perezoso: Prefect es pesado

            inventory_performance_daily_flow(
                trigger="manual", triggered_by=triggered_by, date_from=window[0] if window else None,
                date_to=window[1] if window else None, run_id=run_id,
            )
        except Exception:  # noqa: BLE001 — el flow ya dejó el error estructurado en pipeline_runs
            logger.exception("la corrida manual %s terminó con error (ver reporting.pipeline_runs)", run_id)

    threading.Thread(target=_run, name=f"inventory-performance-{run_id}", daemon=True).start()


def trigger_inventory_performance_run(
    engine: Engine, triggered_by: int | None, date_from: date | None = None, date_to: date | None = None
) -> dict[str, str]:
    """Dispara una corrida manual del MISMO flow que el cron (sin duplicar lógica). Devuelve `{run_id, status}`.

    Lanza `ValueError` si el rango es inválido y `PipelineAlreadyRunning` si ya hay una corrida activa.
    Si dos disparos casi simultáneos pasaran esta comprobación, el candado del flow
    (`acquire_run_lock_and_start_run`) deja a la segunda como `skipped_locked`: nunca corren dos a la vez.
    """
    window = resolve_window(date_from, date_to)
    db.ensure_reporting_schema(engine)
    with engine.connect() as connection:
        active = connection.execute(
            text(
                "SELECT run_id FROM reporting.pipeline_runs WHERE pipeline_name = :name AND status = 'running' "
                "AND heartbeat_at > now() - make_interval(secs => :timeout) LIMIT 1"
            ),
            {"name": settings.PIPELINE_NAME, "timeout": settings.HEARTBEAT_TIMEOUT.total_seconds()},
        ).scalar()
    if active is not None:
        raise PipelineAlreadyRunning(str(active))
    run_id = str(uuid4())
    _launch_flow(run_id, triggered_by, window)
    return {"run_id": run_id, "status": "queued"}


# --------------------------------------------------------------------------- #
# 3 · Consulta de KPIs (el feed del dashboard de la Parte 3)
# --------------------------------------------------------------------------- #
def query_inventory_kpis(engine: Engine, filters: KpiFilters) -> dict[str, Any]:
    """Filas de `reporting.restaurant_inventory_daily` (día) o agregadas por semana, con los filtros dados.

    Sin fechas: los últimos 14 días hasta hoy (UTC). Lanza `InvalidKpiFilters` si los filtros no son válidos.
    """
    if filters.granularity not in GRANULARITIES:
        raise InvalidKpiFilters(f"granularity debe ser una de {GRANULARITIES}")
    date_to = filters.date_to or datetime.now(timezone.utc).date()
    date_from = filters.date_from or (date_to - timedelta(days=DEFAULT_KPI_DAYS - 1))
    if date_from > date_to:
        raise InvalidKpiFilters("from no puede ser posterior a to")
    if (date_to - date_from).days + 1 > settings.MAX_RANGE_DAYS:
        raise InvalidKpiFilters(f"el rango máximo es de {settings.MAX_RANGE_DAYS} días")

    db.ensure_reporting_schema(engine)
    conditions = ["d.report_date BETWEEN :date_from AND :date_to"]
    params: dict[str, Any] = {"date_from": date_from, "date_to": date_to}
    if filters.restaurant:
        conditions.append("d.restaurant = :restaurant")
        params["restaurant"] = filters.restaurant
    if filters.country:
        conditions.append("r.country = :country")
        params["country"] = filters.country
    with engine.connect() as connection:
        frame = pd.read_sql(
            text(
                "SELECT d.*, r.country FROM reporting.restaurant_inventory_daily d "
                "JOIN reporting.dim_restaurant r ON r.restaurant = d.restaurant "
                f"WHERE {' AND '.join(conditions)} ORDER BY d.report_date, d.restaurant"
            ),
            connection,
            params=params,
        )
    if filters.granularity == "week":
        frame = kpi.aggregate_weekly(frame)
    items = frame[KPI_ITEM_COLUMNS] if not frame.empty else pd.DataFrame(columns=KPI_ITEM_COLUMNS)
    numeric = [column for column in KPI_ITEM_COLUMNS if column not in ("report_date", "restaurant", "country", "capture_health")]
    items = items.assign(**{column: pd.to_numeric(items[column], errors="coerce") for column in numeric})  # Decimal → float
    cleaned = items.astype(object).where(items.notna(), None)
    records = [
        _plain({key: (value.item() if hasattr(value, "item") else value) for key, value in row.items()})
        for row in cleaned.to_dict("records")
    ]
    return {"items": records, "generated_at": _iso(datetime.now(timezone.utc))}
