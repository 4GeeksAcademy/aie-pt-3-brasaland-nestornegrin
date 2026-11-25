"""Plazos del BRIEFING: "Día N" cuenta el día de inicio como día 1 y solo días hábiles (lunes a viernes; los festivos no se modelan).
El plazo vence a las 18:00 hora local de la sede (Medellín: America/Bogota; Miami: America/New_York)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config


def is_business_day(day: date) -> bool:
    return day.weekday() < 5


def first_business_day(day: date) -> date:
    while not is_business_day(day):
        day += timedelta(days=1)
    return day


def nth_business_day(start: date, n: int) -> date:
    """Día hábil número `n` (1 = el de inicio, o el primer hábil posterior si empieza en fin de semana)."""
    day = first_business_day(start)
    for _ in range(n - 1):
        day = first_business_day(day + timedelta(days=1))
    return day


def deadline_at(start: date, day_number: int, site: str) -> datetime:
    local = datetime.combine(nth_business_day(start, day_number), time(config.DEADLINE_HOUR_LOCAL), tzinfo=ZoneInfo(config.SITES[site]))
    return local.astimezone(timezone.utc)


def business_days_between(earlier: datetime, later: datetime, site: str) -> int:
    """Días hábiles completos transcurridos desde `earlier` hasta `later` (0 si `later` no es posterior), según el calendario de la sede."""
    zone = ZoneInfo(config.SITES[site])
    start, end = earlier.astimezone(zone).date(), later.astimezone(zone).date()
    days, day = 0, start
    while day < end:
        day += timedelta(days=1)
        if is_business_day(day):
            days += 1
    return days if later > earlier else 0
