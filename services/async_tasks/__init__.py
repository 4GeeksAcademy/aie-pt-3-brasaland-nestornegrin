"""Cola de tareas asíncronas (DEV-55): Celery + Redis.

Layout:
    services/celery_app.py            instancia de Celery (broker + result backend = Redis)
    services/async_tasks/config.py    constantes y variables de entorno
    services/async_tasks/staging.py   guarda el CSV subido; el mensaje de la cola solo lleva su identificador
    services/async_tasks/base.py      clase base de tareas: al agotar reintentos escribe en la DLQ
    services/async_tasks/dlq.py       tabla `task_dead_letters` (Dead Letter Queue en base de datos)
    services/async_tasks/results.py   último resultado del análisis (lo lee el endpoint de exportación)
    services/async_tasks/status.py    estado de Celery → estado de la API (pending/started/success/failure)
    services/async_tasks/observability.py  logs por tarea (task_id, intento, estado, duración, error)
    services/async_tasks/incident_tasks.py  la tarea: análisis del CSV de incidencias
"""
