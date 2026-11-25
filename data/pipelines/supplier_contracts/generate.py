"""Genera los datos de PRUEBA del briefing: 4 contratos PDF ficticios (cada término es una cláusula numerada; fechas relativas a la fecha de
carga) y el histórico de precios CSV con los escenarios A–D en el último mes. Todo determinista: mismo día de carga → mismos ficheros.

Las cláusulas de facturación incluyen a propósito datos bancarios y contactos personales FICTICIOS (ver SENSITIVE_VALUES) para poder
comprobar que el sistema no los propaga."""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from . import config
from .pdfgen import PAGE_BREAK, build_pdf

PRICE_FILE = "price_history.csv"

# Valores ficticios que NUNCA deben aparecer fuera del PDF (las pruebas los buscan en BD, logs, mensajes y respuestas).
SENSITIVE_VALUES = (
    "123-456789-01", "Bancolombia", "juan.perez.personal@gmail.com", "+57 300 123 4567",
    "0012345678", "021000021", "mike.rivera.home@outlook.com", "+1 (305) 555-0142",
    "310-998877-22", "ana.mejia.casa@hotmail.com", "+57 311 765 4321", "0098765432", "061000104", "sam.lee.personal@yahoo.com", "+1 (786) 555-0199",
)
_BILLING = {
    "CT-BR-01": ("Cuenta de ahorros No. 123-456789-01 de Bancolombia a nombre de Carnes del Valle S.A.S. Contacto de facturación: Juan Pérez, "
                 "teléfono personal +57 300 123 4567, correo personal juan.perez.personal@gmail.com."),
    "CT-BR-02": ("Bank account No. 0012345678, routing number 021000021, holder Sunshine Prime Meats. Billing contact: Mike Rivera, "
                 "personal phone +1 (305) 555-0142, personal email mike.rivera.home@outlook.com."),
    "CT-BR-03": ("Cuenta corriente No. 310-998877-22 de Bancolombia a nombre de Avícola Antioquia. Contacto de facturación: Ana Mejía, "
                 "teléfono personal +57 311 765 4321, correo personal ana.mejia.casa@hotmail.com."),
    "CT-BR-04": ("Bank account No. 0098765432, routing number 061000104, holder Brava Beverages FL. Billing contact: Sam Lee, "
                 "personal phone +1 (786) 555-0199, personal email sam.lee.personal@yahoo.com."),
}


def _money_es(amount: Decimal, currency: str) -> str:
    return f"{currency} {int(amount):,}".replace(",", ".")


def _money_en(amount: Decimal, currency: str) -> str:
    return f"{currency} {int(amount):,}"


def contract_lines(contract_id: str, load_date: date) -> list[str]:
    """Texto del contrato `contract_id`, con una cláusula por término. Los saltos de página fijan en qué página cae cada cláusula."""
    spec = next(c for c in config.CONTRACTS if c.id == contract_id)
    supplier = config.SUPPLIER_BY_ID[spec.supplier_id]
    expiry = (load_date + timedelta(days=spec.expires_in_days)).isoformat()
    es = spec.language == "es"
    money = (_money_es if es else _money_en)(spec.annual_value, spec.currency)
    ct = contract_id

    if es:
        head = [f"CONTRATO DE SUMINISTRO {ct}", "(Documento ficticio de prueba)", "",
                f"Entre Brasaland (el Comprador) y {supplier.name} (el Proveedor), con sede en {supplier.country}, se acuerda lo siguiente.", ""]
        c1 = ["Cláusula 1. Objeto. El Proveedor suministrará a Brasaland productos de la categoría " + supplier.category + "."]
        c2 = [f"Cláusula 2. Vencimiento. El presente contrato vence el {expiry}."]
        if ct == "CT-BR-01":
            c3 = ["Cláusula 3. No renovación. Cualquiera de las partes podrá no renovar el contrato con un preaviso de 60 días antes del vencimiento."]
            c4 = ["Cláusula 4. Revisión de precios. Los precios se revisarán semestralmente. El incremento no podrá superar el IPC anual de Colombia "
                  "más 1 punto porcentual, previo preaviso escrito de 30 días."]
            c5 = ["Cláusula 5. Terminación anticipada. Cualquiera de las partes podrá terminar el contrato con un preaviso de 60 días, sin penalización."]
        else:  # CT-BR-03: sin cláusula de preaviso
            c3 = ["Cláusula 3. Entregas. Las entregas se realizarán en los locales de Brasaland en los horarios acordados."]
            c4 = ["Cláusula 4. Revisión de precios. Los precios se revisarán anualmente, con un incremento máximo del 5%."]
            c5 = ["Cláusula 5. Terminación anticipada. Cualquiera de las partes podrá terminar el contrato con un preaviso de 90 días, sin penalización."]
        c6 = [f"Cláusula 6. Valor. El valor anual estimado del contrato es de {money}."]
        c7 = ["Cláusula 7. Facturación y pago. " + _BILLING[ct]]
        c8 = ["Cláusula 8. Ley aplicable. Este contrato se rige por las leyes de la República de Colombia."]
    else:
        head = [f"SUPPLY AGREEMENT {ct}", "(Fictitious test document)", "",
                f"Between Brasaland (the Buyer) and {supplier.name} (the Supplier), based in Florida, USA, the parties agree as follows.", ""]
        c1 = [f"Clause 1. Purpose. The Supplier will supply Brasaland with products in the category {supplier.category}."]
        c2 = [f"Clause 2. Expiry. This agreement expires on {expiry}."]
        if ct == "CT-BR-02":
            c3 = ["Clause 3. Renewal. This agreement renews automatically for 12 months unless either party gives notice 45 days before the expiry date."]
            c4 = ["Clause 4. Price review. Prices are fixed during the term, unless the reference beef index rises more than 10% in the quarter, "
                  "subject to 30 days' written notice."]
            c5 = ["Clause 5. Early termination. Early termination carries a penalty of 2 months of average purchases."]
        else:  # CT-BR-04
            c3 = ["Clause 3. Non-renewal. Either party may decline to renew this agreement by giving notice 15 days before the expiry date."]
            c4 = ["Clause 4. Price review. Prices are free, according to the Supplier's quarterly price list."]
            c5 = ["Clause 5. Early termination. Either party may terminate early with no penalty."]
        c6 = [f"Clause 6. Value. The estimated annual value of this agreement is {money}."]
        c7 = ["Clause 7. Billing and payment. " + _BILLING[ct]]
        c8 = ["Clause 8. Governing law. This agreement is governed by the laws of the State of Florida."]
    # páginas: 1 = partes, objeto y vencimiento · 2 = preaviso, precios y salida · 3 = valor, facturación y ley aplicable
    return head + c1 + [""] + c2 + [PAGE_BREAK] + c3 + [""] + c4 + [""] + c5 + [PAGE_BREAK] + c6 + [""] + c7 + [""] + c8


def _month(d: date, back: int) -> str:
    y, m = d.year, d.month - back
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}"


def _round(price: Decimal, currency: str) -> Decimal:
    return price.quantize(Decimal("1")) if currency == "COP" else price.quantize(Decimal("0.0001"))


def price_rows(load_date: date) -> list[dict]:
    """12 meses por proveedor. Los 11 primeros: ±1 % mensual como máximo, terminando EXACTAMENTE en el precio base. Último mes: escenario del
    briefing (A/B/C/D) o ±1 % para el resto."""
    rows: list[dict] = []
    for supplier_id, product, unit, base, volume in config.PRICE_BASES:
        currency = config.SUPPLIER_BY_ID[supplier_id].currency
        rng = random.Random(f"{supplier_id}-prices")
        series = [base]                                   # el mes 11 (penúltimo) vale el precio base
        for _ in range(10):                               # hacia atrás: cada mes anterior difiere ≤ 1 %
            step = Decimal(rng.randint(-100, 100)) / Decimal(10000)
            series.append(series[-1] / (Decimal(1) + step))
        series.reverse()                                  # meses 1..11
        last_pct = config.SCENARIOS.get(supplier_id, Decimal(rng.randint(-100, 100)) / Decimal(100))
        series.append(base * (Decimal(1) + last_pct / Decimal(100)))
        for i, price in enumerate(series):
            rows.append({"supplier_id": supplier_id, "product": product, "unit": unit, "currency": currency,
                         "month": _month(load_date, 11 - i), "unit_price": str(_round(price, currency)), "monthly_volume": volume})
    return rows


def generate(out_dir: Path, load_date: date) -> dict:
    """Escribe `price_history.csv` y `CT-BR-0x.pdf` en `out_dir`. Devuelve {csv, contracts}."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / PRICE_FILE
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["supplier_id", "product", "unit", "currency", "month", "unit_price", "monthly_volume"])
        writer.writeheader()
        writer.writerows(price_rows(load_date))
    pdfs = []
    for spec in config.CONTRACTS:
        path = out_dir / f"{spec.id}.pdf"
        path.write_bytes(build_pdf(contract_lines(spec.id, load_date)))
        pdfs.append(path)
    return {"csv": csv_path, "contracts": pdfs}
