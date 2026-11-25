"""Encolar el email de restablecimiento (lado API). Devuelve el task_id; mismo `idempotency_key` → mismo task_id y NADA nuevo en la cola."""
from __future__ import annotations

import logging
import uuid

from services.async_tasks import contracts, idempotency

logger = logging.getLogger(__name__)
_NAMESPACE = uuid.UUID("6f1f0a38-0c1e-4c63-9a53-0d2d6f4c9b11")


def enqueue_password_reset_email(to_email: str, token: str, idempotency_key: str) -> str:
    from services.async_tasks.email_tasks import send_password_reset

    store = idempotency.get_store()
    task_id = str(uuid.uuid5(_NAMESPACE, idempotency_key))  # determinista: la misma operación es siempre la misma tarea
    existing = store.claim_enqueue(idempotency_key, task_id)
    if existing is not None:
        logger.info("enqueue key=%s duplicate=skipped task_id=%s", idempotency_key, existing)
        return existing
    try:
        send_password_reset.apply_async(kwargs={"idempotency_key": idempotency_key, "sealed": contracts.seal(to_email, token)}, task_id=task_id)
    except Exception:
        store.release_enqueue(idempotency_key)  # no llegó a la cola: que pueda volver a intentarse
        raise
    return task_id
