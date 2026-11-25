"""Programación: tercer día hábil de cada mes a las 06:00 hora de Medellín (America/Bogota, UTC-5). `tick(now)` es idempotente por periodo."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import config

TZ = ZoneInfo(config.SCHEDULE_TZ)


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in config.HOLIDAYS


def third_business_day(year: int, month: int, n: int = config.SCHEDULE_BUSINESS_DAY) -> date:
    d, count = date(year, month, 1), 0
    while True:
        if is_business_day(d):
            count += 1
            if count == n:
                return d
        d += timedelta(days=1)


def run_at(year: int, month: int) -> datetime:
    return datetime.combine(third_business_day(year, month), datetime.min.time(), TZ).replace(hour=config.SCHEDULE_HOUR)


def period_to_close(now: datetime) -> str:
    """Mes de cierre = último mes completo anterior a la fecha de carga."""
    d = now.astimezone(TZ).date().replace(day=1) - timedelta(days=1)
    return f"{d.year:04d}-{d.month:02d}"


def due(now: datetime) -> tuple[bool, str, datetime]:
    n = now.astimezone(TZ)
    when = run_at(n.year, n.month)
    return n >= when, period_to_close(n), when


def tick(engine, now: datetime, source_dir=None) -> dict:
    """Si ya toca y el periodo no se ha lanzado, lanza el cierre (como proceso automático). Idempotente."""
    ok, period, when = due(now)
    if not ok:
        return {"ran": False, "period": period, "reason": f"aún no es la hora: {when.isoformat()}"}
    return engine.run_scheduled(period, when, source_dir)
