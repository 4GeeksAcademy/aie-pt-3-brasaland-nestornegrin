"""Quién y cómo se registra: traduce una petición (o un proceso) a una entrada del audit log."""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

from fastapi import Request

from .log import AuditLog

logger = logging.getLogger("brasaland.audit")


def note(request: Request, *, user=None, label: str | None = None, resource_id: Any = None, department: str | None = None,
         details: dict[str, Any] | None = None) -> None:
    """Los manejadores aportan al registro lo que solo ellos saben (quién acaba de iniciar sesión, antes/después de un cambio…).
    El middleware lo recoge al terminar la petición; los manejadores no escriben en el log directamente."""
    state = request.state
    if user is not None:
        state.audit_user = user
    if label is not None:
        state.audit_label = label
    if resource_id is not None:
        state.audit_resource_id = str(resource_id)
    if department is not None:
        state.audit_department = department
    if details:
        state.audit_details = {**getattr(state, "audit_details", {}), **details}


def actor_fields(user, label: str | None) -> dict[str, Any]:
    """Actor de una acción. Persona o agente según `account_type` (lo fija un Admin en el servidor, nunca el cliente)."""
    if user is not None:
        return {"actor_type": "agent" if getattr(user, "account_type", "human") == "agent" else "user", "actor_id": str(user.id),
                "actor_label": str(user.email), "actor_role": user.role, "actor_department": user.department}
    handle = (label or "").strip().lower()
    fingerprint = hashlib.sha256(handle.encode()).hexdigest()[:12] if handle else "none"
    return {"actor_type": "anonymous", "actor_id": f"anon:{fingerprint}", "actor_label": handle or None, "actor_role": None, "actor_department": None}


def process_origin(name: str) -> str:
    return f"process:{name}:{os.getpid()}"


def record_process(log: AuditLog, process: str, action: str, *, resource_type: str, resource_id: str | None = None,
                   outcome: str = "success", department: str | None = None, details: dict[str, Any] | None = None) -> None:
    """Acción de un proceso del sistema (worker, tarea programada) — jamás se confunde con una persona: actor_type=system."""
    try:
        log.append(actor_type="system", actor_id=process, actor_label=process, action=action, category="process",
                   resource_type=resource_type, resource_id=resource_id, department=department, outcome=outcome,
                   origin=process_origin(process), channel="process", details=details)
    except Exception:  # noqa: BLE001 - un fallo del registro no debe tumbar la tarea, pero tiene que hacer ruido
        logger.critical("No se pudo escribir en el audit log (proceso %s, acción %s)", process, action, exc_info=True)
