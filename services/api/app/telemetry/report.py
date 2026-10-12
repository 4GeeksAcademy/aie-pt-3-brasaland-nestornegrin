"""Capa de servicio de `GET /telemetry/report`: ventana de fechas y caché.

El endpoint solo orquesta: resuelve el período UNA vez, consulta la caché y, si no
hay resultado vigente, llama al pipeline de `analysis.py`. Ningún cálculo vive aquí.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Callable

from fastapi import HTTPException
from sqlmodel import Session

from app.telemetry.analysis import build_metrics

DEFAULT_WINDOW = timedelta(days=7)
MAX_WINDOW = timedelta(days=90)
CACHE_TTL_SECONDS = 60
CACHE_MAX_ENTRIES = 64


def _as_utc(value: datetime) -> datetime:
    """Normaliza a UTC; una fecha sin zona horaria se interpreta como UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def resolve_period(
    start_date: datetime | None,
    end_date: datetime | None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> tuple[datetime, datetime]:
    """Ventana `[start, end)` en UTC. Por defecto: los últimos 7 días hasta ahora."""
    end = _as_utc(end_date) if end_date is not None else now()
    start = _as_utc(start_date) if start_date is not None else end - DEFAULT_WINDOW
    if start >= end:
        raise HTTPException(status_code=400, detail="start_date debe ser anterior a end_date")
    if end - start > MAX_WINDOW:
        raise HTTPException(status_code=400, detail=f"El período no puede superar {MAX_WINDOW.days} días")
    return start, end


def _iso_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class ReportCache:
    """Caché simple en memoria con TTL, segura entre hilos.

    La clave es lo que PIDIÓ el cliente (`start_date`/`end_date` tal cual, o `None`):
    así las peticiones por defecto (sin parámetros) también reutilizan el resultado,
    aunque «ahora» cambie en cada llamada. Un solo candado cubre consulta + cálculo,
    de modo que dos peticiones simultáneas no calculan el mismo informe dos veces.
    """

    def __init__(self, ttl_seconds: float = CACHE_TTL_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = Lock()
        self._entries: dict[tuple[str | None, str | None], tuple[float, dict[str, Any]]] = {}

    def get_or_compute(
        self,
        key: tuple[str | None, str | None],
        compute: Callable[[], dict[str, Any]],
    ) -> tuple[dict[str, Any], bool]:
        """Devuelve `(informe, desde_caché)`."""
        with self._lock:
            now = self._clock()
            cached = self._entries.get(key)
            if cached is not None and cached[0] > now:
                return cached[1], True
            report = compute()
            self._entries[key] = (now + self._ttl, report)
            self._evict(now)
            return report, False

    def _evict(self, now: float) -> None:
        """Acota la memoria: quita lo caducado y, si aún sobra, lo que caduca antes."""
        self._entries = {k: v for k, v in self._entries.items() if v[0] > now}
        overflow = len(self._entries) - CACHE_MAX_ENTRIES
        if overflow > 0:
            oldest = sorted(self._entries, key=lambda k: self._entries[k][0])[:overflow]
            self._entries = {k: v for k, v in self._entries.items() if k not in oldest}

    def clear(self) -> None:
        with self._lock:
            self._entries = {}


report_cache = ReportCache()


def get_report(
    session: Session,
    start_date: datetime | None,
    end_date: datetime | None,
    cache: ReportCache | None = None,
) -> tuple[dict[str, Any], bool]:
    """Informe `{"period": {...}, "metrics": {...}}` y si salió de la caché."""
    cache = cache if cache is not None else report_cache
    key = (
        _iso_utc(_as_utc(start_date)) if start_date is not None else None,
        _iso_utc(_as_utc(end_date)) if end_date is not None else None,
    )

    def compute() -> dict[str, Any]:
        start, end = resolve_period(start_date, end_date)  # la ventana se resuelve UNA vez…
        return {
            "period": {"from": _iso_utc(start), "to": _iso_utc(end)},
            "metrics": build_metrics(session, start, end),  # …y se pasa igual a todas las métricas
        }

    return cache.get_or_compute(key, compute)
