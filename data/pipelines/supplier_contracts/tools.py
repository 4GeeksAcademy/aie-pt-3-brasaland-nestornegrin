"""Herramientas DETERMINISTAS de cálculo. El modelo/los agentes NUNCA hacen aritmética: llaman a estas funciones (todas con Decimal, sin
estado, cubiertas por pruebas). Cada resultado se entrega redondeado de forma explícita para que sea reproducible."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from . import config

LB_PER_KG = Decimal("2.2046226218")
_TWO = Decimal("0.01")


def q2(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


def pct_change(previous: Decimal, current: Decimal) -> Decimal:
    """Variación porcentual (2 decimales). El precio anterior debe ser > 0."""
    if previous <= 0:
        raise ValueError("el precio anterior debe ser positivo")
    return q2((current - previous) / previous * 100)


def threshold_for(category: str) -> Decimal:
    """Umbral de alerta de subida: carne de res > 3 %, resto de categorías > 8 % (BRIEFING)."""
    return config.PRICE_THRESHOLD_BEEF_PCT if category == config.BEEF else config.PRICE_THRESHOLD_OTHER_PCT


def exceeds_threshold(pct: Decimal, category: str) -> bool:
    return pct > threshold_for(category)


def monthly_impact(previous: Decimal, current: Decimal, volume: int) -> Decimal:
    """Coste mensual extra = (precio nuevo − precio anterior) × volumen mensual."""
    return q2((current - previous) * Decimal(volume))


def convert(amount: Decimal, source: str, target: str) -> Decimal:
    """Conversión al tipo de cambio de referencia (1 USD = 4.000 COP)."""
    if source == target:
        return q2(amount)
    if source == "USD" and target == "COP":
        return q2(amount * config.FX_COP_PER_USD)
    if source == "COP" and target == "USD":
        return q2(amount / config.FX_COP_PER_USD)
    raise ValueError(f"conversión no soportada: {source}→{target}")


def to_usd(amount: Decimal, currency: str) -> Decimal:
    return convert(amount, currency, "USD")


def price_per_kg_usd(price: Decimal, unit: str, currency: str) -> Decimal:
    """Precio por kg en USD (solo para comparaciones ORIENTATIVAS entre mercados distintos)."""
    usd = price / config.FX_COP_PER_USD if currency == "COP" else price
    if unit == "lb":
        usd = usd * LB_PER_KG
    elif unit != "kg":
        raise ValueError(f"unidad no comparable: {unit}")
    return q2(usd)


def peer_gap(own: Decimal, peer: Decimal, volume: int) -> tuple[Decimal, Decimal, Decimal]:
    """(diferencia absoluta peer−own, diferencia %, ahorro mensual al volumen actual si se comprara al peer)."""
    diff = peer - own
    return q2(diff), pct_change(own, peer), q2(-diff * Decimal(volume))


def cpi_cap(points: Decimal) -> Decimal:
    """Tope de revisión «IPC anual de Colombia + N puntos»."""
    return q2(config.COLOMBIA_CPI + points)


def days_between(start: date, end: date) -> int:
    return (end - start).days


def notice_deadline(expiry: date, notice_days: int) -> date:
    return expiry - timedelta(days=notice_days)


def expiry_stage(days_left: int) -> int | None:
    """Etapa de alerta de vencimiento alcanzada: 30 (≤ 30 días), 90 (≤ 90 días) o None."""
    for stage in sorted(config.EXPIRY_ALERT_DAYS):
        if days_left <= stage:
            return stage
    return None


def notice_due(days_to_deadline: int) -> bool:
    """¿Hay que avisar? Faltan 15 días o menos para la fecha límite de preaviso (o ya se pasó)."""
    return days_to_deadline <= config.NOTICE_ALERT_DAYS


def fmt_es(value: Decimal, places: int = 2) -> str:
    """12345.6 → 12.345,60 (formato es-CO), solo para mostrar."""
    text = f"{value:,.{places}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".")
