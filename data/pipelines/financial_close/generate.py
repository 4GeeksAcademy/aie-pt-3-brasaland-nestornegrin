"""Genera los tres CSV de prueba del briefing para el MES DE CIERRE (último mes completo antes de la fecha de carga): `ledger.csv`,
`budget.csv` y `operations.csv`. Cada partida tiene VARIOS registros cuya suma coincide exactamente con la cifra real del briefing; en las
compras la descripción lleva proveedor, precio unitario y cantidad. Servicios de Florida no tiene registros. La nómina va solo agregada por
país. Para comprobar que no se propagan, algunas compras llevan datos bancarios FICTICIOS en la descripción (SENSITIVE_VALUES)."""
from __future__ import annotations

import csv
from calendar import monthrange
from datetime import date
from decimal import Decimal
from pathlib import Path

from . import config

SENSITIVE_VALUES = ("123-456789-01", "Bancolombia No.", "0012345678", "021000021")
_BANK_NOTE = {"CO": " | Pago a cuenta Bancolombia No. 123-456789-01", "FL": " | Wire: account 0012345678, routing 021000021"}
LEDGER_COLUMNS = ["entry_id", "date", "country", "category", "description", "currency", "amount", "source_ref"]


def closing_period(load_date: date) -> str:
    """Mes de cierre = último mes completo antes de la fecha de carga (YYYY-MM)."""
    y, m = (load_date.year, load_date.month - 1) if load_date.month > 1 else (load_date.year - 1, 12)
    return f"{y:04d}-{m:02d}"


def _split(total: Decimal, n: int, currency: str = "USD") -> list[Decimal]:
    """Reparte `total` en n partes (COP sin decimales, USD con 2); la última absorbe el resto, así la suma es EXACTA."""
    part = (total / n).quantize(Decimal("1") if currency == "COP" else Decimal("0.01"))
    parts = [part] * (n - 1)
    return parts + [total - sum(parts, Decimal(0))]


def _num(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text


def _day(period: str, i: int, n: int) -> str:
    y, m = int(period[:4]), int(period[5:])
    last = monthrange(y, m)[1]
    return date(y, m, max(1, min(last, round(last * (i + 1) / n) - 1))).isoformat()


_DESC = {"Ingresos por ventas": "Ventas de los locales – semana {i}", "Nómina": "Nómina agregada del país – quincena {i}",
         "Alquileres": "Alquiler de locales – bloque {i}", "Marketing": "Gasto de marketing – factura MK-{n:04d}",
         "Servicios": "Servicios públicos – recibo {i}"}


def ledger_rows(period: str) -> list[dict]:
    rows: list[dict] = []
    seq = {"CO": 0, "FL": 0}
    for line in config.LINES:
        if line.actual is None:
            continue                                                     # Servicios Florida: SIN REGISTROS
        name, currency = config.COUNTRIES[line.country]
        income = line.category == config.INCOME
        n = line.deliveries
        if line.supplier:                                                # compra: proveedor, precio unitario y cantidad en la descripción
            qty_parts = _split(line.actual_quantity, n)
            amounts = [line.actual_unit_price * q for q in qty_parts]
            assert sum(amounts) == line.actual, (line.label, sum(amounts), line.actual)
        else:
            qty_parts = [None] * n
            amounts = _split(line.actual, n, currency)
        for i in range(n):
            seq[line.country] += 1
            if line.supplier:
                desc = (f"Compra a proveedor {line.supplier}; precio unitario {_num(line.actual_unit_price)} {currency}/{line.unit}; "
                        f"cantidad {_num(qty_parts[i])} {line.unit}")
                if i == 0:
                    desc += _BANK_NOTE[line.country]
                ref = f"FAC-{''.join(w[0] for w in line.supplier.split()).upper()}-{1000 + seq[line.country]}"
            else:
                desc = _DESC[line.category].format(i=i + 1, n=1000 + seq[line.country])
                ref = {"Ingresos por ventas": f"POS-{line.country}-{period}-W{i + 1}", "Nómina": f"NOM-AGG-{line.country}-{period}-Q{i + 1}"}.get(
                    line.category, f"DOC-{line.country}-{config.CATEGORY_KEY[line.category]}-{1000 + seq[line.country]}")
            rows.append({"entry_id": f"L-{line.country}-{period}-{seq[line.country]:04d}", "date": _day(period, i, n), "country": name,
                         "category": line.category, "description": desc, "currency": currency,
                         "amount": _num(amounts[i] if income else -amounts[i]), "source_ref": ref})
    return rows


def budget_rows(period: str) -> list[dict]:
    return [{"month": period, "country": config.COUNTRIES[l.country][0], "category": l.category, "currency": config.COUNTRIES[l.country][1],
             "amount": _num(l.budget)} for l in config.LINES]


def operations_rows(period: str) -> list[dict]:
    rows = []
    for (cc, metric), (budget, actual) in config.OPERATIONS.items():
        for suffix, value in (("budget", budget), ("actual", actual)):
            rows.append({"month": period, "country": config.COUNTRIES[cc][0], "metric": f"{metric}_{suffix}", "value": _num(value)})
    for line in config.LINES:
        if line.supplier:
            key = config.CATEGORY_KEY[line.category].lower()
            for metric, value in ((f"{key}_unit_price_budget", line.unit_price), (f"{key}_quantity_budget", line.quantity)):
                rows.append({"month": period, "country": config.COUNTRIES[line.country][0], "metric": metric, "value": _num(value)})
    return rows


def _write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def generate(out_dir: Path, load_date: date) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    period = closing_period(load_date)
    _write(out_dir / "ledger.csv", LEDGER_COLUMNS, ledger_rows(period))
    _write(out_dir / "budget.csv", ["month", "country", "category", "currency", "amount"], budget_rows(period))
    _write(out_dir / "operations.csv", ["month", "country", "metric", "value"], operations_rows(period))
    return {"period": period, "dir": out_dir}
