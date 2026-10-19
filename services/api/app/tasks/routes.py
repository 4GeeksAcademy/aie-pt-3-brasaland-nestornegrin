"""GET /tasks/{task_id}: estado (y resultado, cuando existe) de una tarea asíncrona (DEV-55)."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from kombu.exceptions import OperationalError
from redis.exceptions import RedisError

from app.auth.dependencies import get_current_user
from services.async_tasks.status import describe_task

logger = logging.getLogger(__name__)


def create_router() -> APIRouter:
    router = APIRouter(tags=["tasks"], dependencies=[Depends(get_current_user)])

    @router.get("/tasks/{task_id}")
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
