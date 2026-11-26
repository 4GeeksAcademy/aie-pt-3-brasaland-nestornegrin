"""Ingesta de las tres fuentes del cierre (`ledger.csv`, `budget.csv`, `operations.csv`) a un formato común, conservando SIEMPRE su origen
(fichero + fila). Todo registro incompleto o inconsistente se marca DUDOSO con sus motivos y no se usa en las cifras: nunca se da por válido.
La descripción se redacta (datos bancarios, salarios individuales) ANTES de guardarla."""
from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import config, tools
from .sensitive import MARK, clean, clean_any, is_individual_payroll, redact
from .store import DataStore, now

_COUNTRY_CODE = {name: code for code, (name, _) in config.COUNTRIES.items()}
_LEDGER_REQUIRED = ("entry_id", "date", "country", "category", "currency", "amount")


def _dec(text: str | None) -> Decimal | None:
    try:
        return Decimal((text or "").strip())
    except InvalidOperation:
        return None


def _in_period(text: str, period: str) -> bool:
    try:
        d = date.fromisoformat(text)
    except ValueError:
        return False
    return f"{d.year:04d}-{d.month:02d}" == period


def check_ledger(row: dict, period: str, seen: set[str]) -> list[str]:
    reasons: list[str] = []
    missing = [f for f in _LEDGER_REQUIRED if not (row.get(f) or "").strip()]
    if missing:
        reasons.append("registro incompleto: falta " + ", ".join(missing))
    code = _COUNTRY_CODE.get((row.get("country") or "").strip())
    if row.get("country") and code is None:
        reasons.append(f"país desconocido: {row['country']}")
    if code and row.get("currency") and row["currency"].strip() != config.COUNTRIES[code][1]:
        reasons.append(f"moneda {row['currency']} inconsistente con {row['country']} ({config.COUNTRIES[code][1]})")
    amount = _dec(row.get("amount"))
    if row.get("amount") and amount is None:
        reasons.append(f"importe no numérico: {row['amount']}")
    category = (row.get("category") or "").strip()
    if category and category not in config.CATEGORIES:
        reasons.append(f"partida desconocida: {category}")
    if amount is not None and category in config.CATEGORIES:
        if (category == config.INCOME) != (amount > 0):
            reasons.append("signo inconsistente: los ingresos son positivos y los gastos negativos")
    if row.get("date") and not _in_period(row["date"], period):
        reasons.append(f"fecha fuera del mes de cierre {period} o ilegible: {row['date']}")
    eid = (row.get("entry_id") or "").strip()
    if eid and eid in seen:
        reasons.append(f"entry_id duplicado: {eid}")
    if category in config.PURCHASE_CATEGORIES and amount is not None:
        p = tools.parse_purchase(row.get("description") or "")
        if p is None:
            reasons.append("compra sin proveedor/precio unitario/cantidad legibles en la descripción")
        elif abs(p["unit_price"] * p["quantity"] - abs(amount)) > Decimal("0.01"):
            reasons.append("importe incoherente con precio unitario × cantidad")
    if category == "Nómina" and is_individual_payroll(row.get("description") or ""):
        reasons.append("línea de nómina por persona: la nómina solo se admite agregada por país")
    return reasons


def ingest(data: DataStore, files_dir: Path, period: str) -> dict:
    files_dir = Path(files_dir)
    with data.conn() as c:
        c.execute("DELETE FROM records WHERE period=?", (period,))
    stats = {"ledger": [0, 0], "budget": [0, 0], "operations": [0, 0], "redacted": 0}

    def put(kind, fname, rowno, **f):
        reasons = clean_any(f.pop("reasons"))                 # los motivos citan el valor crudo (p. ej. un importe con una cuenta): se redactan ANTES de guardar
        f = {k: (clean(v) if isinstance(v, str) else v) for k, v in f.items()}
        status = "doubtful" if reasons else "valid"
        stats[kind][1 if reasons else 0] += 1
        data.run("INSERT INTO records(period,kind,file,row,entry_id,date,country,category,currency,amount,description,source_ref,metric,status,reasons) "
                 "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (period, kind, fname, rowno, f.get("entry_id"), f.get("date"), f.get("country"), f.get("category"), f.get("currency"),
                  f.get("amount"), f.get("description"), f.get("source_ref"), f.get("metric"), status, json.dumps(reasons, ensure_ascii=False)))

    seen: set[str] = set()
    with (files_dir / "ledger.csv").open(encoding="utf-8", newline="") as fh:
        for rowno, row in enumerate(csv.DictReader(fh), start=2):                  # fila 1 = cabecera
            reasons = check_ledger(row, period, seen)
            if (row.get("entry_id") or "").strip():
                seen.add(row["entry_id"].strip())
            desc, kinds = redact(row.get("description"))
            if kinds:
                stats["redacted"] += 1
            if is_individual_payroll(row.get("description") or ""):
                desc = MARK
            put("ledger", "ledger.csv", rowno, entry_id=(row.get("entry_id") or "").strip(), date=row.get("date"),
                country=_COUNTRY_CODE.get((row.get("country") or "").strip()), category=(row.get("category") or "").strip(),
                currency=(row.get("currency") or "").strip(), amount=(row.get("amount") or "").strip(), description=desc,
                source_ref=redact(row.get("source_ref"))[0], reasons=reasons)
    seen_budget: set[tuple] = set()
    with (files_dir / "budget.csv").open(encoding="utf-8", newline="") as fh:
        for rowno, row in enumerate(csv.DictReader(fh), start=2):
            reasons = []
            code = _COUNTRY_CODE.get((row.get("country") or "").strip())
            if not all((row.get(k) or "").strip() for k in ("month", "country", "category", "currency", "amount")):
                reasons.append("presupuesto incompleto")
            if row.get("month") and row["month"].strip() != period:
                reasons.append(f"mes {row['month']} distinto del mes de cierre {period}")
            if row.get("country") and code is None:
                reasons.append(f"país desconocido: {row['country']}")
            if code and row.get("currency") and row["currency"].strip() != config.COUNTRIES[code][1]:
                reasons.append("moneda inconsistente con el país")
            if row.get("amount") and _dec(row["amount"]) is None:
                reasons.append(f"importe no numérico: {row['amount']}")
            if (row.get("category") or "").strip() not in config.CATEGORIES:
                reasons.append(f"partida desconocida: {row.get('category')}")
            key = (code, (row.get("category") or "").strip())
            if key in seen_budget:
                reasons.append("presupuesto duplicado para la misma partida")
            seen_budget.add(key)
            put("budget", "budget.csv", rowno, country=code, category=(row.get("category") or "").strip(), currency=(row.get("currency") or "").strip(),
                amount=(row.get("amount") or "").strip(), reasons=reasons)
    with (files_dir / "operations.csv").open(encoding="utf-8", newline="") as fh:
        for rowno, row in enumerate(csv.DictReader(fh), start=2):
            reasons = []
            code = _COUNTRY_CODE.get((row.get("country") or "").strip())
            if not all((row.get(k) or "").strip() for k in ("month", "country", "metric", "value")):
                reasons.append("indicador incompleto")
            if row.get("month") and row["month"].strip() != period:
                reasons.append(f"mes {row['month']} distinto del mes de cierre {period}")
            if row.get("country") and code is None:
                reasons.append(f"país desconocido: {row['country']}")
            if row.get("value") and _dec(row["value"]) is None:
                reasons.append(f"valor no numérico: {row['value']}")
            put("operations", "operations.csv", rowno, country=code, metric=(row.get("metric") or "").strip(), amount=(row.get("value") or "").strip(), reasons=reasons)
    summary = {k: {"valid": v[0], "doubtful": v[1]} for k, v in stats.items() if k != "redacted"} | {"redacted_descriptions": stats["redacted"]}
    data.run("INSERT OR REPLACE INTO loads(period, loaded_at, summary) VALUES(?,?,?)", (period, now(), json.dumps(summary)))
    return summary
