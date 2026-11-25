"""GET /tasks/{task_id}: estado (y resultado, cuando existe) de una tarea asíncrona (DEV-55)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from kombu.exceptions import OperationalError
from pydantic import BaseModel
from redis.exceptions import RedisError

from app.auth.dependencies import get_current_user
from app.access.models import Action
from app.access.permissions import require_access
from services.async_tasks import dlq
from services.async_tasks.status import describe_task

logger = logging.getLogger(__name__)


class TaskStatusResponse(BaseModel):
    """Contrato de `GET /tasks/{task_id}` (ver `services.async_tasks.status.describe_task`)."""

    task_id: str
    status: Literal["pending", "started", "success", "failure"]
    result: dict[str, Any] | None = None
    attempts: int | None = None  # ejecuciones que ha tenido la tarea (reintentos + 1); `None` si aún no arrancó


class DeadLetterItem(BaseModel):
    """Una tarea que agotó sus reintentos (tabla `task_dead_letters`)."""

    id: int
    task_id: str
    task_name: str
    attempt: int  # ejecución en la que se rindió (0 = ni siquiera llegó a la cola)
    error_message: str
    failed_at: datetime


def create_router() -> APIRouter:
    router = APIRouter(tags=["tasks"], dependencies=[Depends(get_current_user)])

    @router.get("/tasks/dead-letters", response_model=list[DeadLetterItem], dependencies=[Depends(require_access(Action.ADMINISTER))])
    def list_dead_letters(limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
        """La cola de mensajes fallidos, vista por un Admin: nada que agote sus reintentos desaparece en silencio."""
        try:
            return dlq.list_dead_letters(limit)
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo leer la dead-letter queue")
            raise HTTPException(status_code=503, detail="No se pudo leer la cola de mensajes fallidos.") from None

    @router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
    def get_task_status(task_id: str) -> dict[str, Any]:
        """`{"task_id", "status": pending | started | success | failure, "result"}`.

        `result` es el resumen del análisis cuando `status` es `success`, `{"error": ...}` cuando es `failure`
        y `null` en cualquier otro caso. Un id desconocido figura como `pending` (así lo reporta Celery).
        """
        try:
            uuid.UUID(task_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Tarea no encontrada") from None
        try:
            return describe_task(task_id)
        except (RedisError, OperationalError, OSError):
            logger.exception("No se pudo consultar el estado de la tarea %s", task_id)
            raise HTTPException(status_code=503, detail="La cola de tareas no está disponible. Inténtalo de nuevo en unos segundos.") from None

    return router
