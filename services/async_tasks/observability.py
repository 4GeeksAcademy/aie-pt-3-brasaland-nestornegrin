"""Logs por tarea: task_id, intento, estado resultante y duración; los fallos añaden el error completo.

Formato (una línea por ejecución terminada):
    task=incidents.analyze_csv task_id=<uuid> attempt=2 status=retry duration_ms=3 error=<...>
Cada intento cuenta como una ejecución: `attempt` = reintentos ya hechos + 1.
"""
from __future__ import annotations

import logging
import time

from celery.signals import task_failure, task_postrun, task_prerun, task_retry, task_success

logger = logging.getLogger("brasaland.tasks")

_started_at: dict[str, float] = {}
_final_status: dict[str, str] = {}  # estado que decide success/retry/failure antes de `task_postrun`


def _attempt(task) -> int:
    return (task.request.retries or 0) + 1


def _duration_ms(task_id: str) -> int:
    started = _started_at.pop(task_id, None)
    return round((time.perf_counter() - started) * 1000) if started is not None else -1


@task_prerun.connect(weak=False)
def _on_prerun(task_id=None, task=None, **_):
    _started_at[task_id] = time.perf_counter()
    logger.info("task=%s task_id=%s attempt=%d status=started", task.name, task_id, _attempt(task))


@task_success.connect(weak=False)
def _on_success(sender=None, **_):
    _final_status[sender.request.id] = "success"


@task_retry.connect(weak=False)
def _on_retry(sender=None, request=None, reason=None, **_):
    _final_status[request.id] = "retry"
    logger.warning(
        "task=%s task_id=%s attempt=%d status=retry error=%s",
        sender.name,
        request.id,
        (request.retries or 0) + 1,
        reason,
    )


@task_failure.connect(weak=False)
def _on_failure(sender=None, task_id=None, exception=None, traceback=None, einfo=None, **_):
    _final_status[task_id] = "failure"
    # Error completo: tipo + mensaje + traceback (exc_info lo imprime en el log del worker).
    logger.error(
        "task=%s task_id=%s attempt=%d status=failure error=%s: %s",
        sender.name,
        task_id,
        _attempt(sender),
        type(exception).__name__,
        exception,
        exc_info=(type(exception), exception, traceback) if traceback is not None else None,
    )


@task_postrun.connect(weak=False)
def _on_postrun(task_id=None, task=None, **_):
    status = _final_status.pop(task_id, "unknown")
    logger.info(
        "task=%s task_id=%s attempt=%d status=%s duration_ms=%d",
        task.name,
        task_id,
        _attempt(task),
        status,
        _duration_ms(task_id),
    )
