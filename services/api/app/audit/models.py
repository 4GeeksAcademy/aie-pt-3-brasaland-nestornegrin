"""Registro de auditoría: responde a «quién hizo qué, sobre qué recurso, cuándo y desde dónde».

No es un log técnico (errores, latencia, trazas): prioriza INMUTABILIDAD (cadena HMAC), COMPLETITUD (cubre toda acción sensible,
no solo errores) y ATRIBUCIÓN (siempre hay un actor identificado: persona, agente automatizado o proceso del sistema).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ActorType = Literal["user", "agent", "system", "anonymous"]  # persona · agente automatizado · proceso · sin identificar (login fallido)
Outcome = Literal["success", "failure", "denied"]
Channel = Literal["http", "process"]
Category = Literal["auth", "access", "federated", "audit", "process", "data"]

# Eventos de SEGURIDAD de la plataforma (sesiones, permisos, proveedores externos, el propio audit log, procesos del sistema).
# Los ve solo un Admin del departamento Tecnología. El resto («data») son acciones sobre datos de negocio y se reparten por departamento.
SECURITY_CATEGORIES: frozenset[str] = frozenset({"auth", "access", "federated", "audit", "process"})

GENESIS_HASH = "0" * 64


class AuditEntry(BaseModel):
    """Una entrada del registro. Una vez escrita no se actualiza ni se borra: `hash` encadena con la anterior (HMAC)."""

    seq: int = Field(ge=1)
    id: str
    timestamp: datetime
    # ---- quién
    actor_type: ActorType
    actor_id: str  # id de usuario, nombre del proceso o huella del identificador intentado (login fallido)
    actor_label: str | None = None  # correo en ese momento (informativo)
    actor_role: str | None = None
    actor_department: str | None = None
    # ---- qué y sobre qué
    action: str  # p. ej. supplier.rate_change
    category: Category
    resource_type: str
    resource_id: str | None = None
    department: str | None = None  # departamento dueño del recurso (reparte la visibilidad del visor)
    outcome: Outcome = "success"
    # ---- desde dónde
    origin: str  # IP del cliente o identificador del proceso (process:<nombre>:<pid>)
    channel: Channel = "http"
    details: dict[str, Any] = Field(default_factory=dict)  # cambios antes/después; nunca secretos
    # ---- evidencia de alteración
    prev_hash: str
    hash: str


class VerifyResult(BaseModel):
    valid: bool
    entries: int
    head_seq: int
    head_hash: str
    broken_at_seq: int | None = None
    reason: str | None = None


class AuditPage(BaseModel):
    items: list[AuditEntry]
    total: int  # coincidencias con los filtros que el usuario puede ver
    limit: int
    next_before_seq: int | None = None  # cursor: pide la página siguiente con before_seq=<este valor>


class AuditFacets(BaseModel):
    actions: list[str]
    resource_types: list[str]
    categories: list[str]
    can_view_security: bool
