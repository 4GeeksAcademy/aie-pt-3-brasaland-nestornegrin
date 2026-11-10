"""Contratos (pydantic) de lo que devuelve cada agente. Todo lo que sale de un modelo de lenguaje se VALIDA contra estos
esquemas antes de usarse o guardarse: un JSON mal formado o con campos de más no llega a la base de datos."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class Signals(_Strict):
    """Señales que el clasificador debe confirmar en el documento (criterios del BRIEFING §2.2)."""
    service_requested: bool = False  # catering recurrente, concesión o co-branding
    scope_or_volume: bool = False  # comensales, ubicaciones, duración del contrato…
    deadline: bool = False  # fecha límite para responder
    budget: bool = False  # rango de presupuesto


class Classification(_Strict):
    is_rfp: bool
    document_type: Literal["rfp_formal", "rfp_informal", "consulta_general", "otro"] = "otro"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    signals: Signals = Field(default_factory=Signals)
    reasons: list[str] = Field(default_factory=list)


class RfpMetadata(_Strict):
    """Metadatos del BRIEFING §2.3. Todo lo que el documento no diga queda en None y se anota en `open_questions`."""
    reference: str | None = None  # nº de referencia de la RFP si lo trae
    client_name: str | None = None
    location: str | None = None
    service_type: str | None = None
    scope: str | None = None
    deadline: str | None = None  # tal como lo dice el documento
    deadline_iso: str | None = None  # AAAA-MM-DD solo si el documento da día, mes y año
    budget_range: str | None = None
    budget_usd_min: float | None = None  # solo si el documento lo expresa en USD
    budget_usd_max: float | None = None
    open_questions: list[str] = Field(default_factory=list)


class DepartmentAssignment(_Strict):
    department_id: str
    reason: str = ""
    excerpts: list[str] = Field(default_factory=list)  # fragmentos TEXTUALES del documento relevantes para ese departamento


class Plan(_Strict):
    assignments: list[DepartmentAssignment]
    unknown_departments: list[str] = Field(default_factory=list)  # nombres que el modelo no pudo mapear a un id válido


class KeyAspect(_Strict):
    aspect: str
    detail: str = ""
    source_excerpt: str = ""  # cita textual del documento que lo respalda
    unverified_numbers: list[str] = Field(default_factory=list)  # cifras que el modelo escribió y NO aparecen en la RFP
    inferred: bool = False  # True si la cita NO figura textualmente en el PDF (el aspecto es una inferencia del worker, no un dato del documento)


class Finding(_Strict):
    department_id: str
    key_aspects: list[KeyAspect] = Field(default_factory=list)
    asks: list[str] = Field(default_factory=list)  # qué hay que pedirle a ese departamento
    figures: dict[str, str] = Field(default_factory=dict)  # cifras que SÍ están en la RFP, p. ej. {"comensales": "220"}
    open_questions: list[str] = Field(default_factory=list)  # datos que faltan en la RFP para ese departamento

    @field_validator("figures", mode="before")
    @classmethod
    def _stringify(cls, value):
        return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}


class SalesSummary(_Strict):
    headline: str = ""
    by_department: dict[str, str] = Field(default_factory=dict)  # texto breve «qué pedir a quién» por departamento
