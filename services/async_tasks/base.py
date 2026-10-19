"""Clase base de las tareas: Dead Letter Queue al agotar los reintentos."""
from __future__ import annotations

from celery import Task

from services.async_tasks import dlq


class DeadLetterTask(Task):
    """`on_failure` solo se ejecuta cuando la tarea falla DEFINITIVAMENTE: con `self.retry(exc=...)`, mientras
    queden reintentos Celery lanza `Retry` (que no pasa por aquí); al agotarlos relanza la excepción original."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        dlq.record_dead_letter(
            task_id=task_id,
            task_name=self.name,
            attempt=(self.request.retries or 0) + 1,  # nº de ejecución en la que se rindió (reintentos + el intento inicial)
            error_message=f"{type(exc).__name__}: {exc}",
        )
        self.cleanup_after_final_failure(args, kwargs)

    def cleanup_after_final_failure(self, args, kwargs) -> None:
        """Hook para liberar recursos de la tarea (p. ej. el fichero aparcado). Por defecto, nada."""
