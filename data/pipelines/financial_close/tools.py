"""Herramientas DETERMINISTAS de cálculo del cierre. El agente decide QUÉ calcular; estas funciones lo calculan (Decimal, sin estado, con
pruebas). Mismos datos → mismas cifras, siempre. Nunca se suman importes de monedas distintas sin convertirlos antes."""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from . import config


class CurrencyMixError(ValueError):
    pass


def q1(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def sum_amounts(items: Iterable[tuple[Decimal, str]]) -> tuple[Decimal, str | None]:
    """(suma, moneda). Falla si hay más de una moneda: primero hay que convertir."""
    total, currency = Decimal(0), None
    for amount, cur in items:
        if currency is not None and cur != currency:
            raise CurrencyMixError(f"no se pueden sumar {currency} y {cur} sin convertir")
        currency = cur
        total += amount
    return total, currency


def variance_abs(actual: Decimal, budget: Decimal) -> Decimal:
    """Desviación absoluta = real − presupuesto."""
    return actual - budget


def variance_pct(actual: Decimal, budget: Decimal) -> Decimal | None:
    """Desviación % exacta (sin redondear) sobre el presupuesto; None si el presupuesto es 0."""
    if budget == 0:
        return None
    return (actual - budget) / budget * 100


def is_relevant_deviation(pct: Decimal | None) -> bool:
    """Relevante si |desviación| ≥ 5 % (a favor o en contra). Se compara SIN redondear."""
    return pct is not None and abs(pct) >= config.THRESHOLD_PCT


def pct_change(old: Decimal, new: Decimal) -> Decimal | None:
    return None if old == 0 else (new - old) / old * 100


def convert_currency(amount: Decimal, source: str, target: str) -> Decimal:
    if source == target:
        return amount
    if source == "COP" and target == "USD":
        return amount / config.FX_COP_PER_USD
    if source == "USD" and target == "COP":
        return amount * config.FX_COP_PER_USD
    raise ValueError(f"conversión no soportada: {source}→{target}")


def to_usd(amount: Decimal, currency: str) -> Decimal:
    return q2(convert_currency(amount, currency, "USD"))


def consolidate_usd(items: Iterable[tuple[Decimal, str]]) -> Decimal:
    """Convierte CADA importe a USD (al tipo del briefing) y suma ya en USD."""
    return sum((to_usd(a, c) for a, c in items), Decimal(0))


_PURCHASE = re.compile(r"proveedor (?P<supplier>.+?); precio unitario (?P<price>[\d.]+) (?P<cur>[A-Z]{3})/(?P<unit>\w+); cantidad (?P<qty>[\d.]+) (?P<qunit>\w+)")


def parse_purchase(description: str) -> dict | None:
    """Lee proveedor, precio unitario y cantidad de la descripción de una compra; None si no se puede leer con certeza."""
    m = _PURCHASE.search(description or "")
    if not m or m["unit"] != m["qunit"]:
        return None
    return {"supplier": m["supplier"], "unit_price": Decimal(m["price"]), "currency": m["cur"], "unit": m["unit"], "quantity": Decimal(m["qty"])}


def price_volume_effect(actual_price: Decimal, actual_qty: Decimal, budget_price: Decimal, budget_qty: Decimal) -> tuple[Decimal, Decimal]:
    """Descompone real − presupuesto = efecto precio + efecto cantidad (suma EXACTA): precio = (pa−pb)·qa, cantidad = (qa−qb)·pb."""
    return (actual_price - budget_price) * actual_qty, (actual_qty - budget_qty) * budget_price


def fmt(value: Decimal, places: int = 2) -> str:
    """12345.6 → 12.345,60 (formato es-CO), solo para mostrar."""
    return f"{value:,.{places}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def fmt_pct(value: Decimal | None) -> str:
    return "n/d" if value is None else f"{q1(value):+.1f}%".replace(".", ",")
