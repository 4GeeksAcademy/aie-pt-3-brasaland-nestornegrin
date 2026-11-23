"""Validación de rangos de fechas compartida por el flow (`pipeline.py`) y la API (`api.py`)."""
from __future__ import annotations

from datetime import date

from data.pipelines.inventory_performance import settings


def resolve_window(date_from: date | None, date_to: date | None) -> tuple[date, date] | None:
    """Rango manual de recálculo: sin fechas → None (incremental); con una sola, un único día.

    Lanza `ValueError` si el rango está invertido o supera `settings.MAX_RANGE_DAYS`.
    """
    if date_from is None and date_to is None:
        return None
    start, end = date_from or date_to, date_to or date_from
    if start > end:
        raise ValueError("date_from no puede ser posterior a date_to")
    if (end - start).days + 1 > settings.MAX_RANGE_DAYS:
        raise ValueError(f"el rango máximo es de {settings.MAX_RANGE_DAYS} días")
    return start, end
