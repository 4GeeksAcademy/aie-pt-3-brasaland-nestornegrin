"""Tipos compartidos de la memoria del agente (sin lógica)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# Categorías memorables (BRIEFING «Qué SÍ vale la pena recordar»). Cualquier otra se rechaza en la política.
CATEGORY_SCHEDULES = "horarios"
CATEGORY_SUPPLIERS = "proveedores"
CATEGORY_KNOWN_INCIDENTS = "incidentes_conocidos"
CATEGORY_COMMUNICATION = "preferencias_comunicacion"
CATEGORY_EXCEPTIONS = "excepciones_procedimiento"
CATEGORIES = (CATEGORY_SCHEDULES, CATEGORY_SUPPLIERS, CATEGORY_KNOWN_INCIDENTS, CATEGORY_COMMUNICATION,
              CATEGORY_EXCEPTIONS)

# Estados de una propuesta (tabla `proposals`).
PROPOSAL_PENDING = "pending"
PROPOSAL_APPROVED = "approved"
PROPOSAL_EDITED = "edited"  # el usuario aprobó con su propia redacción
PROPOSAL_REJECTED = "rejected"
PROPOSAL_DISCARDED = "discarded"  # ambigua, cambio de tema, edición inválida, límite o caducada

# Estados de un recuerdo (tabla `memories`).
MEMORY_ACTIVE = "active"
MEMORY_SUPERSEDED = "superseded"
MEMORY_EXPIRED = "expired"
MEMORY_EVICTED = "evicted"


class Intent(str, Enum):
    """Lo que el usuario hizo con la propuesta pendiente."""

    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"
    AMBIGUOUS = "ambiguous"  # silencio, otro tema o respuesta poco clara: NUNCA se interpreta como aprobación


@dataclass(frozen=True)
class MemoryProposal:
    location: str
    category: str
    topic: str  # etiqueta corta y estable del dato (p. ej. «proveedor_carne»); sirve para reemplazar versiones viejas
    fact: str  # frase que se guardaría tal cual, lo que ve el usuario
    rationale: str
    language: str = "es"


@dataclass(frozen=True)
class Decision:
    intent: Intent
    confidence: float = 0.0
    edited_fact: str | None = None
    remainder: str = ""  # parte del mensaje que NO trata sobre la propuesta (p. ej. otra pregunta)


@dataclass(frozen=True)
class StructuredAnswer:
    """Salida de la única llamada al modelo: lo que ve el usuario y, si aplica, la propuesta de memoria."""

    answer: str
    proposal: dict | None = None


@dataclass(frozen=True)
class Resolution:
    """Resultado de evaluar el mensaje del usuario contra la propuesta pendiente."""

    kind: str  # approved | edited | rejected | discarded
    notice: str
    remainder: str
    proposal_id: str
    reason: str = ""
    memory_id: str | None = None
    language: str = "es"

    def to_dict(self) -> dict:
        return {"kind": self.kind, "proposal_id": self.proposal_id, "reason": self.reason, "memory_id": self.memory_id}


@dataclass(frozen=True)
class ProposalOutcome:
    proposal_id: str
    proposal: MemoryProposal
    question: str  # texto que se añade al final de la respuesta
    replaces: str | None = None

    def to_dict(self) -> dict:
        return {"proposal_id": self.proposal_id, "location": self.proposal.location,
                "category": self.proposal.category, "fact": self.proposal.fact, "replaces": self.replaces}


@dataclass
class ConsolidationReport:
    expired: int = 0
    duplicates: int = 0
    evicted: int = 0
    pending_discarded: int = 0
    kept: int = 0
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"expired": self.expired, "duplicates": self.duplicates, "evicted": self.evicted,
                "pending_discarded": self.pending_discarded, "kept": self.kept}
