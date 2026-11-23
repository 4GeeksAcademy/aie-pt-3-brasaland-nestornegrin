"""Tarea asíncrona: análisis del CSV de incidencias (antes se ejecutaba dentro de la petición HTTP)."""
from __future__ import annotations

import dataclasses
from typing import Any

from scripts.analyze import analyze_csv_text
from services.async_tasks import config, results, staging
from services.async_tasks.base import DeadLetterTask
from services.celery_app import celery_app


class _AnalyzeIncidentsTask(DeadLetterTask):
    def cleanup_after_final_failure(self, args, kwargs) -> None:
        if args:
            staging.delete_upload(args[0])


@celery_app.task(
    bind=True,
    base=_AnalyzeIncidentsTask,
    name=config.ANALYZE_INCIDENTS_TASK,
    max_retries=config.MAX_RETRIES,
    soft_time_limit=config.SOFT_TIME_LIMIT_SECONDS,  # toda tarea tiene timeout
    time_limit=config.HARD_TIME_LIMIT_SECONDS,
    acks_late=True,  # el mensaje se confirma (ACK) solo tras terminar: si el worker muere a medias, vuelve a la cola
)
def analyze_incidents_csv(self, upload_id: str) -> dict[str, Any]:
    """Analiza el CSV aparcado en `upload_id` y devuelve el resumen (un dict pequeño, no el contenido del CSV).

    El mensaje de la cola solo lleva `upload_id`. Cualquier excepción se reintenta con backoff exponencial;
    al agotar `max_retries` Celery relanza el error y `DeadLetterTask.on_failure` lo registra en la DLQ.
    """
    try:
        result = analyze_csv_text(staging.read_upload_text(upload_id))
        payload = dataclasses.asdict(result)
        results.store_latest(payload)
    except Exception as error:
        raise self.retry(exc=error, countdown=config.backoff_seconds(self.request.retries))
    staging.delete_upload(upload_id)
    return payload
