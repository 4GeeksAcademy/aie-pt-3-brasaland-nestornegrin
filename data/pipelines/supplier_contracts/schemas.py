"""Contratos de ENTRADA y SALIDA de los agentes. Es la única forma de hablar entre agentes: los especialistas no se conocen entre sí
y el supervisor solo ve estos modelos (nunca PDFs ni filas crudas). Todo `Fact` lleva su origen; todo `Citation` lleva cláusula y página."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRef(_Model):
    file: str
    row: int = Field(ge=1, description="fila del CSV de origen (la 1 es la cabecera)")


class Fact(_Model):
    """Una cifra con su procedencia: de qué filas sale."""
    key: str
    label: str
    value: str
    unit: str = ""
    sources: list[SourceRef] = []


class Citation(_Model):
    """Una afirmación contractual con su cláusula y página, en el idioma del contrato."""
    contract_id: str
    file: str
    clause: str
    page: int = Field(ge=1)
    quote: str
    language: Literal["es", "en"]
    confidence: float = Field(ge=0, le=1)
    doubtful: bool = False


# ------------------------------------------------------------------ especialista de PRECIOS
class PriceRequest(_Model):
    action: Literal["history", "detect_increase", "peers", "full_report"]
    supplier_id: str
    as_of: date
    compare_with: str | None = Field(default=None, description="otro proveedor (otro país) para una comparación orientativa")


class IncreaseInfo(_Model):
    supplier_id: str
    product: str
    unit: str
    currency: str
    month: str
    previous_price: Decimal
    current_price: Decimal
    pct: Decimal
    threshold_pct: Decimal
    exceeds: bool
    monthly_volume: int
    monthly_impact: Decimal | None = None          # en la moneda del proveedor
    monthly_impact_usd: Decimal | None = None
    annualized_impact: Decimal | None = None
    sources: list[SourceRef]


class PeerQuote(_Model):
    supplier_id: str
    name: str
    price: Decimal
    unit: str
    currency: str
    quote_only: bool
    diff_abs: Decimal
    diff_pct: Decimal
    monthly_saving: Decimal | None = None          # sobre el volumen mensual del proveedor actual
    indicative: bool = False                       # True si cruza países (mercados distintos)
    note: str = ""
    source: SourceRef


class PriceResponse(_Model):
    status: Literal["ok", "no_data", "not_found"]
    supplier_id: str
    supplier_name: str = ""
    category: str = ""
    country: str = ""
    increase: IncreaseInfo | None = None
    history: list[Fact] = []
    peers: list[PeerQuote] = []
    notes: list[str] = []
    missing: list[str] = []


# ------------------------------------------------------------------ especialista de CONTRATOS
class ContractRequest(_Model):
    action: Literal["terms", "evaluate_increase", "deadlines", "notice"]
    supplier_id: str
    as_of: date
    increase_pct: Decimal | None = None


class Term(_Model):
    kind: Literal["expiry", "renewal_notice", "price_review", "exit", "annual_value"]
    clause: str
    page: int
    quote: str
    language: Literal["es", "en"]
    confidence: float
    doubtful: bool
    params: dict


class Deadline(_Model):
    kind: Literal["expiry", "notice_deadline"]
    date: date
    days_left: int
    citation: Citation


class IncreaseVerdict(_Model):
    verdict: Literal["permitted", "not_permitted", "indeterminate"]
    increase_pct: Decimal
    allowed_max_pct: Decimal | None = None
    reasons: list[str]
    pending_conditions: list[str] = []


class ContractResponse(_Model):
    status: Literal["ok", "no_contract", "not_found"]
    supplier_id: str
    supplier_name: str = ""
    contract_id: str | None = None
    language: str | None = None
    annual_value: Decimal | None = None
    annual_value_currency: str | None = None
    annual_value_usd: Decimal | None = None
    exit_penalty_estimate: Decimal | None = None      # penalización de salida estimada en la moneda del contrato (si la cláusula la fija)
    terms: list[Term] = []
    verdict: IncreaseVerdict | None = None
    deadlines: list[Deadline] = []
    citations: list[Citation] = []
    missing: list[str] = []
    message: str = ""


# ------------------------------------------------------------------ SUPERVISOR
class SupervisorReply(_Model):
    intent: str
    supplier_id: str | None = None
    answer: str
    consulted: list[str]
    consults_used: int
    consults_limit: int
    facts: list[Fact] = []
    citations: list[Citation] = []
    missing: list[str] = []
    truncated: bool = False
    brief: dict | None = None
