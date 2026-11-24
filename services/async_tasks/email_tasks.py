"""Tarea asíncrona: email de restablecimiento de contraseña (servicio externo: Resend).

Antes se enviaba DENTRO de la petición `POST /auth/forgot-password`: si Resend tardaba, el usuario esperaba; si fallaba, el
error se tragaba con un log y el email se perdía sin que nadie lo supiera. Ahora la petición solo encola; este worker:

  1. comprueba la clave de idempotencia (si ya se envió con éxito, no repite);
  2. llama al proveedor; si falla, reintenta con backoff exponencial (2 s, 4 s, 8 s);
  3. si agota los reintentos, la tarea cae en la dead-letter queue (`task_dead_letters`) y queda visible.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from services.async_tasks import config, contracts, idempotency
from services.async_tasks.base import DeadLetterTask
from services.celery_app import celery_app

logger = logging.getLogger(__name__)
_API_DIR = Path(__file__).resolve().parents[1] / "api"


def send_password_reset_email(to_email: str, token: str, idempotency_key: str | None = None) -> None:
    """Proveedor externo (Resend). Separado para poder simularlo en las pruebas."""
    if str(_API_DIR) not in sys.path:
        sys.path.insert(0, str(_API_DIR))  # el worker puede arrancar desde la raíz del monorepo
    from app.auth.email import send_password_reset_email as send

    send(to_email, token, idempotency_key=idempotency_key)


class _EmailTask(DeadLetterTask):
    """Marca de la clase: las fallidas definitivas liberan además el cerrojo de idempotencia (otro intento manual podría reenviarlo)."""

    def cleanup_after_final_failure(self, args, kwargs) -> None:
        key = kwargs.get("idempotency_key")
        if key:
            try:
                idempotency.get_store().release(key)
            except Exception:  # noqa: BLE001
                logger.exception("No se pudo liberar el cerrojo de idempotencia %s", key)


@celery_app.task(
    bind=True,
    base=_EmailTask,
    name=config.SEND_PASSWORD_RESET_TASK,
    max_retries=config.MAX_RETRIES,
    soft_time_limit=60,  # un email no debería tardar: toda tarea tiene timeout
    time_limit=90,
    acks_late=True,
)
def send_password_reset(self, idempotency_key: str, sealed: str) -> dict[str, Any]:
    attempt = (self.request.retries or 0) + 1
    store = idempotency.get_store()
    try:
        store.record_attempt(self.request.id, attempt)  # nº de intentos consultable (GET /tasks/{id})
    except Exception:  # noqa: BLE001 - la observabilidad nunca debe impedir el trabajo
        logger.warning("No se pudo registrar el intento de %s", self.request.id)

    # Si el mensaje es ilegible o caducó, `unseal` lanza InvalidMessage: es imposible por definición, así que no se reintenta
    # (no pasa por `self.retry`): la tarea falla ya y `DeadLetterTask.on_failure` la deja en la DLQ.
    to_email, token = contracts.unseal(sealed)

    state = store.begin(idempotency_key)
    if state == "done":
        logger.info("task=%s key=%s duplicate=skipped", self.name, idempotency_key)
        return {"status": "duplicate_skipped", "attempts": attempt}
    if state == "busy":
        raise self.retry(exc=RuntimeError("la misma operación se está procesando en otro worker"), countdown=config.backoff_seconds(self.request.retries))

    try:
        send_password_reset_email(to_email, token, idempotency_key=idempotency_key)
    except Exception as error:
        store.release(idempotency_key)  # sin cerrojo, el siguiente intento puede entrar
        raise self.retry(exc=error, countdown=config.backoff_seconds(self.request.retries))
    store.complete(idempotency_key)
    return {"status": "sent", "attempts": attempt}
