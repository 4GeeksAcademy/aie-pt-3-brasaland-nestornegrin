"""Modelos de petición/respuesta de `/reporting/inventory-performance/*` (diseño §9.1)."""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    """Cuerpo opcional del disparo manual: sin fechas, corrida incremental; con fechas, recalcula ese rango."""

    date_from: date | None = Field(default=None, description="Primer día local a recalcular (YYYY-MM-DD)")
    date_to: date | None = Field(default=None, description="Último día local a recalcular (YYYY-MM-DD)")


class RunQueuedResponse(BaseModel):
    run_id: str
    status: str = "queued"


class PipelineStatusResponse(BaseModel):
    last_run: dict[str, Any] | None = Field(description="Metadata de la última corrida (estado, inicio, fin, registros procesados, errores…)")
    last_success_at: str | None
    watermark_lag: int = Field(description="Eventos de telemetría que aún no ha procesado ninguna carga confirmada")
    is_running: bool
    active_run_id: str | None
    is_stale: bool = Field(description="True si la última corrida exitosa tiene más de 26 h (el cron no corrió)")
    capture_health: dict[str, int] = Field(description="Cubos recientes por salud de captura: ok / real_zero / suspected_capture_gap")


class KpiItem(BaseModel):
    """Una fila de `reporting.restaurant_inventory_daily` (o su agregado semanal)."""

    report_date: date
    restaurant: str
    country: str
    outbound_orders: int  # K1
    units_issued: float  # K2
    spoilage_units: float
    spoilage_rate_pct: float | None  # K3
    stock_alerts_low: int  # K4
    stock_alerts_critical: int
    validation_failures: int
    validation_rejection_rate_pct: float | None  # K5
    ingredients_at_risk_eod: int  # K6
    ingredients_critical_eod: int
    telemetry_coverage_pct: float | None
    events_deduplicated: int
    capture_health: str
    revision: int


class KpisResponse(BaseModel):
    items: list[KpiItem]
    generated_at: str
