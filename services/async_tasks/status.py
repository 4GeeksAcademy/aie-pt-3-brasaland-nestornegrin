"""Estado de una tarea para `GET /tasks/{task_id}`."""
from __future__ import annotations

from typing import Any

from celery.result import AsyncResult

from services.celery_app import celery_app

# Estados reales de Celery → estados de la API. RETRY (esperando el siguiente intento) se muestra como `started`:
# la tarea ya arrancó y sigue viva; el contrato solo admite pending | started | success | failure.
_STATE_TO_STATUS = {
    "PENDING": "pending",
    "RECEIVED": "pending",
    "STARTED": "started",
    "RETRY": "started",
    "SUCCESS": "success",
    "FAILURE": "failure",
    "REVOKED": "failure",
}


def describe_task(task_id: str) -> dict[str, Any]:
    """Consulta el estado en el result backend (Redis). Lanza el error de conexión si Redis no responde.

    Nota: Celery no distingue «tarea que no existe» de «tarea aún no recogida»: un id desconocido es `pending`.
    """
    async_result = AsyncResult(task_id, app=celery_app)
    status = _STATE_TO_STATUS.get(async_result.state, "pending")
    result: Any = None
    if status == "success":
        result = async_result.result
    elif status == "failure":
        error = async_result.result  # en FAILURE, `result` es la excepción
        result = {"error": f"{type(error).__name__}: {error}"}
    return {"task_id": task_id, "status": status, "result": result}
