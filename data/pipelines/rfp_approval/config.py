"""Constantes de la Parte 3 (aprobación humana y cierre). Todo lo que sale del company-BRIEFING lleva su referencia."""
from __future__ import annotations

import os

from data.pipelines.rfp_intake.departments import CEO_APPROVAL_THRESHOLD_USD, CEO_NAME, DEPARTMENTS, OWNER_DEPARTMENT
from data.pipelines.rfp_response import config as part2

SCHEMA_VERSION = 1

# Estados del ticket de ESTA parte (BRIEFING §2.3). Se llega desde en_evaluación / needs_human_review (Parte 2); no se inventan otros.
STATUS_AWAITING = "esperando_aprobación"
STATUS_DONE = "terminado"
ENTRY_STATUSES = (part2.STATUS_EVALUATING, part2.STATUS_NEEDS_REVIEW)
PART3_STATUSES = (STATUS_AWAITING, STATUS_DONE)

# Estado de aprobación de una sección (BRIEFING §2.3) y acciones posibles del humano.
APPROVAL_PENDING, APPROVAL_APPROVED, APPROVAL_REJECTED = "pendiente", "aprobado", "rechazado"
APPROVE, REJECT, REQUEST_CHANGES = "approve", "reject", "request_changes"
ACTIONS = (APPROVE, REJECT, REQUEST_CHANGES)
MIN_COMMENT_CHARS = 10  # rechazar o pedir cambios exige decir qué corregir: ese texto es el feedback del generador

# La CEO no es un departamento: aprueba una vez que todos los departamentos activos aprobaron (BRIEFING §5/§6/§7).
CEO_ID = "ceo"
ARBITER_NAME = next(d.owner for d in DEPARTMENTS.values() if d.id == OWNER_DEPARTMENT)  # Camila Ospina: dueña del ticket

# Estado de la rama (hilo) de un departamento.
BRANCH_WAITING, BRANCH_IDLE = "esperando", "libre"

# Triggers de conflicto (BRIEFING §7) con su árbitro fijo. Las reglas de detección viven en `arbiter.py`.
TRIGGER_COST, TRIGGER_SLA, TRIGGER_CEO = "cost-vs-feasibility", "setup-sla-breach", "ceo-threshold"

DEFAULT_MAX_ROUNDS = 3


def max_rounds() -> int:
    """Rondas de aprobación por sección (cada vuelta al generador cuenta). Al agotarse, la sección se escala al árbitro."""
    try:
        return max(1, int(os.environ.get("RFP_MAX_APPROVAL_ROUNDS", DEFAULT_MAX_ROUNDS)))
    except ValueError:
        return DEFAULT_MAX_ROUNDS


def thread_id(ticket_id: int, department_id: str | None = None) -> str:
    """Identidad del checkpoint: un hilo por ticket (`rfp-7`) y uno por rama de departamento (`rfp-7:marketing`).
    Dos tickets nunca comparten checkpoint, y la pausa de un departamento no toca el hilo de otro."""
    return f"rfp-{ticket_id}" if department_id is None else f"rfp-{ticket_id}:{department_id}"


def owner_of(department_id: str) -> str:
    return CEO_NAME if department_id == CEO_ID else DEPARTMENTS[department_id].owner


__all__ = ["CEO_APPROVAL_THRESHOLD_USD", "CEO_NAME", "OWNER_DEPARTMENT", "part2"]
