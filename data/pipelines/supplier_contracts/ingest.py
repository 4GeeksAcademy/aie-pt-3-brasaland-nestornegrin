"""Ingesta: (1) registro de proveedores + histórico de precios CSV, conservando fichero y fila de origen; (2) contratos PDF: se extrae el
término de cada cláusula numerada con su cláusula, página, cita literal (en el idioma del contrato) y una confianza. Una extracción de
baja confianza se marca DUDOSA y nunca se usa como si fuera firme. La cláusula de facturación se descarta ENTERA (datos sensibles)."""
from __future__ import annotations

import csv
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pdfplumber

from . import config
from .sensitive import BILLING_MARK, clean
from .store import Store, now

CONFIDENCE_MIN = 0.7
_HEAD = re.compile(r"^(Cláusula|Clause)\s+(\d+)\.\s*(.*)$")
_BILLING = re.compile(r"(?i)factur|billing|payment|pago")
_DAYS = re.compile(r"(\d+)\s*(?:d[ií]as|days)", re.I)
_PCT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_POINTS = re.compile(r"(\d+)\s*(?:punto|point)", re.I)
_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_MONEY = re.compile(r"\b(COP|USD)\s*([\d.,]+\d)")


# ------------------------------------------------------------------ precios
def ingest_prices(store: Store, csv_path: Path) -> int:
    csv_path = Path(csv_path)
    for s in config.SUPPLIERS:
        store.run("INSERT OR REPLACE INTO suppliers(id,name,country,category,currency) VALUES(?,?,?,?,?)", (s.id, s.name, s.country, s.category, s.currency))
    store.run("DELETE FROM prices")
    count = 0
    with csv_path.open(encoding="utf-8", newline="") as fh:
        for line, row in enumerate(csv.DictReader(fh), start=2):          # la fila 1 es la cabecera
            Decimal(row["unit_price"])                                      # valida: falla pronto si el dato es ilegible
            store.run("INSERT INTO prices(supplier_id,product,unit,currency,month,unit_price,monthly_volume,source_file,source_row) VALUES(?,?,?,?,?,?,?,?,?)",
                      (row["supplier_id"], row["product"], row["unit"], row["currency"], row["month"], row["unit_price"],
                       int(row["monthly_volume"]), csv_path.name, line))
            count += 1
    return count


# ------------------------------------------------------------------ contratos
def _amount(text: str, language: str) -> Decimal:
    return Decimal(text.replace(".", "").replace(",", ".")) if language == "es" else Decimal(text.replace(",", ""))


def _classify(text: str) -> str | None:
    t = config.normalize(text)
    if _BILLING.search(t) and re.match(r"^(facturacion|billing)", t):
        return "billing"
    if re.match(r"^(vencimiento|expiry)", t):
        return "expiry"
    if re.match(r"^(no renovacion|renovacion|non-renewal|renewal|preaviso|notice)", t):
        return "renewal_notice"
    if re.match(r"^(revision de precios|price review)", t):
        return "price_review"
    if re.match(r"^(terminacion|rescision|early termination|termination)", t):
        return "exit"
    if re.match(r"^(valor|value)", t):
        return "annual_value"
    return None


def _parse(kind: str, text: str, language: str) -> tuple[dict, float]:
    """(parámetros, confianza). Confianza alta solo si TODOS los parámetros esperados se leyeron."""
    t = config.normalize(text)
    if kind == "expiry":
        m = _DATE.search(text)
        return ({"date": m.group(1)}, 0.97) if m else ({}, 0.4)
    if kind == "annual_value":
        m = _MONEY.search(text)
        return ({"amount": str(_amount(m.group(2), language)), "currency": m.group(1)}, 0.97) if m else ({}, 0.4)
    if kind == "renewal_notice":
        d = _DAYS.search(text)
        mode = "auto_renew_unless_notice" if re.search(r"renueva automaticamente|renews automatically", t) else "non_renewal"
        params: dict = {"mode": mode}
        if d:
            params["notice_days"] = int(d.group(1))
        m = re.search(r"(\d+)\s*(?:meses|months)", t)
        if m and mode == "auto_renew_unless_notice":
            params["renewal_months"] = int(m.group(1))
        return (params, 0.96) if d else (params, 0.45)
    if kind == "exit":
        d = _DAYS.search(text)
        pen = re.search(r"penalizacion de (\d+) meses|penalty of (\d+) months", t)
        params = {}
        if d:
            params["notice_days"] = int(d.group(1))
        if re.search(r"sin penalizacion|no penalty|without penalty", t):
            params["penalty"] = "none"
        elif pen:
            params["penalty"] = "months_of_average_purchases"
            params["penalty_months"] = int(pen.group(1) or pen.group(2))
        if "penalty" in params and ("notice_days" in params or re.search(r"anticipada|early", t)):
            return params, 0.95
        return params, 0.5
    if kind == "price_review":
        pct, pts, d = _PCT.search(text), _POINTS.search(text), _DAYS.search(text)
        freq = "semiannual" if re.search(r"semestral|semiannual", t) else "annual" if re.search(r"anual|annual", t) else "quarterly" if re.search(r"trimest|quarter", t) else None
        base: dict = {"frequency": freq} if freq else {}
        if re.search(r"\bipc\b|\bcpi\b", t):
            if pts:
                base.update(type="cpi_plus", points=int(pts.group(1)))
                if d and re.search(r"escrito|written", t):
                    base.update(written_notice_days=int(d.group(1)))
                return base, 0.96
            return {**base, "type": "cpi_plus"}, 0.5
        if re.search(r"indice de referencia|reference .*index", t):
            if pct:
                base.update(type="fixed_unless_index", index_threshold_pct=str(_amount(pct.group(1), language)), index_period="quarter")
                if d and re.search(r"escrito|written", t):
                    base.update(written_notice_days=int(d.group(1)))
                return base, 0.96
            return {**base, "type": "fixed_unless_index"}, 0.5
        if re.search(r"maximo|maximum|at most", t):
            if pct:
                return {**base, "type": "annual_cap", "cap_pct": str(_amount(pct.group(1), language))}, 0.96
            return {**base, "type": "annual_cap"}, 0.5
        if re.search(r"libres?|\bfree\b|lista de precios|price list", t):
            return {**base, "type": "free_list"}, 0.93
        return base, 0.4
    return {}, 0.4


def extract_terms(pdf_path: Path, language: str, contract_id: str) -> tuple[list[dict], int]:
    """Lee el PDF página a página y devuelve (términos, nº de páginas). Cada término: kind, clause, page, quote, confidence, doubtful, params."""
    terms: list[dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        pages = len(pdf.pages)
        for number, page in enumerate(pdf.pages, start=1):
            current: dict | None = None
            for line in (page.extract_text() or "").splitlines():
                m = _HEAD.match(line.strip())
                if m:
                    current = {"clause": m.group(2), "page": number, "text": m.group(3)}
                    terms.append(current)
                elif current is not None and line.strip():
                    current["text"] += " " + line.strip()
    out: list[dict] = []
    for item in terms:
        kind = _classify(item["text"])
        if kind is None:
            continue                                                   # cláusula sin término relevante (objeto, entregas, ley aplicable)
        if kind == "billing":
            out.append({"kind": "billing", "clause": item["clause"], "page": item["page"], "quote": BILLING_MARK, "confidence": 1.0, "doubtful": False, "params": {}})
            continue
        params, confidence = _parse(kind, item["text"], language)
        out.append({"kind": kind, "clause": item["clause"], "page": item["page"], "quote": clean(item["text"]), "confidence": confidence,
                    "doubtful": confidence < CONFIDENCE_MIN, "params": params})
    return out, pages


def ingest_contract(store: Store, pdf_path: Path, supplier_id: str, language: str) -> dict:
    pdf_path = Path(pdf_path)
    contract_id = pdf_path.stem
    terms, pages = extract_terms(pdf_path, language, contract_id)
    store.run("DELETE FROM terms WHERE contract_id=?", (contract_id,))
    store.run("INSERT OR REPLACE INTO contracts(id,supplier_id,file,language,pages,loaded_at) VALUES(?,?,?,?,?,?)",
              (contract_id, supplier_id, pdf_path.name, language, pages, now()))
    for t in terms:
        if t["kind"] == "billing":
            continue                                                   # no se guarda nada de la cláusula de facturación, ni su texto
        store.run("INSERT INTO terms(contract_id,kind,clause,page,quote,language,confidence,doubtful,params) VALUES(?,?,?,?,?,?,?,?,?)",
                  (contract_id, t["kind"], t["clause"], t["page"], t["quote"], language, t["confidence"], int(t["doubtful"]),
                   json.dumps(t["params"], ensure_ascii=False)))
    return {"contract_id": contract_id, "terms": len([t for t in terms if t["kind"] != "billing"]),
            "doubtful": [t["clause"] for t in terms if t["doubtful"]], "billing_clause_dropped": any(t["kind"] == "billing" for t in terms)}


def ingest_all(store: Store, data_dir: Path, load_date: date) -> dict:
    data_dir = Path(data_dir)
    store.seed_staff()
    store.set_meta("load_date", load_date.isoformat())
    rows = ingest_prices(store, data_dir / "price_history.csv")
    contracts = []
    for spec in config.CONTRACTS:
        contracts.append(ingest_contract(store, data_dir / f"{spec.id}.pdf", spec.supplier_id, spec.language))
        store.run("UPDATE contracts SET supplier_id=? WHERE id=?", (spec.supplier_id, spec.id))
    store.event("system", "system:ingest", "ingest", "", {"price_rows": rows, "contracts": [c["contract_id"] for c in contracts],
                                                         "doubtful": {c["contract_id"]: c["doubtful"] for c in contracts if c["doubtful"]}})
    return {"price_rows": rows, "contracts": contracts}
