"""Instancia de Celery del monorepo (DEV-55).

    API (productor) ──► Redis (broker) ──► worker (consumidor) ──► Redis (result backend)

La API y los workers importan ESTE módulo, así que comparten broker y backend (`REDIS_URL`).
Arrancar el worker (desde `services/api` en Docker, o desde la raíz del monorepo en local):

    celery -A services.celery_app worker --loglevel=info
"""
from __future__ import annotations

from celery import Celery

from services.async_tasks import config

celery_app = Celery(
    "brasaland",
    broker=config.REDIS_URL,
    backend=config.REDIS_URL,
    include=["services.async_tasks.incident_tasks"],  # import perezoso: evita el ciclo celery_app ↔ tareas
)

celery_app.conf.update(
    # Serialización JSON: los mensajes son datos planos y ligeros (identificadores), nunca objetos Python.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # `started` solo existe como estado si se registra expresamente (por defecto Celery salta de PENDING a SUCCESS).
    task_track_started=True,
    # ACK tardío: el broker no da la tarea por entregada hasta que el worker termina bien.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # un worker no acapara mensajes que otro podría procesar
    # Eventos que Flower necesita para mostrar tareas en cola, en proceso y completadas.
    worker_send_task_events=True,
    task_send_sent_event=True,
    # Redis: un mensaje no confirmado (worker muerto a medias) vuelve a la cola pasado este tiempo.
    broker_transport_options={"visibility_timeout": config.VISIBILITY_TIMEOUT_SECONDS},
    broker_connection_retry_on_startup=True,
    # Si Redis está caído, `.delay()` falla rápido (la API responde 503) en vez de colgar la petición.
    broker_connection_timeout=2,
    task_publish_retry_policy={"max_retries": 1, "interval_start": 0, "interval_step": 0.2, "interval_max": 0.5},
    result_expires=24 * 3600,
)

# Registra los handlers de log (señales de Celery). Va aquí, tras crear la instancia, para que lo cargue
# tanto el worker como la API.
from services.async_tasks import observability  # noqa: E402,F401
