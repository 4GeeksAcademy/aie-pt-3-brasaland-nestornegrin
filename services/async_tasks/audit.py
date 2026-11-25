"""Audit log para los workers: las tareas asíncronas escriben en el MISMO registro append-only que la API.

Un worker no es una persona: queda como `actor_type=system`, canal `process`, con su nombre y pid como origen. El registro
nunca debe tumbar la tarea (el trabajo útil ya se hizo), pero un fallo al auditar se registra como CRÍTICO.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
_API_DIR = Path(__file__).resolve().parents[1] / "api"


def record_task(action: str, *, task_id: str | None, outcome: str, details: dict | None = None, process: str = "celery-worker") -> None:
    try:
        if str(_API_DIR) not in sys.path:
            sys.path.insert(0, str(_API_DIR))
        from app.audit.log import AuditLog
        from app.audit.recorder import record_process
        from app.database import AUDIT_HEAD_PATH, AUDIT_LOG_PATH

        record_process(AuditLog(AUDIT_LOG_PATH, AUDIT_HEAD_PATH), process, action, resource_type="incident_analysis", resource_id=task_id,
                       outcome=outcome, department="restaurant_operations", details=details)
    except Exception:  # noqa: BLE001
        logger.critical("No se pudo auditar la tarea %s", task_id, exc_info=True)
