"""Configuración de la cola. Todo lo que cambia entre entornos viene de variables de entorno."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Broker y result backend. Dentro de docker-compose es `redis://redis:6379/0` (nombre del servicio);
# en local, sin Docker, Redis está en localhost.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Reintentos automáticos: 3 reintentos tras el primer fallo (4 ejecuciones como máximo).
MAX_RETRIES = 3
# Backoff exponencial: countdown = base · 2^reintentos_ya_hechos → 2 s, 4 s, 8 s con la base por defecto.
RETRY_BACKOFF_BASE_SECONDS = int(os.environ.get("TASK_RETRY_BASE_SECONDS", "2"))
RETRY_BACKOFF_MAX_SECONDS = int(os.environ.get("TASK_RETRY_MAX_SECONDS", "300"))

# Toda tarea tiene timeout: el soft limit lanza SoftTimeLimitExceeded (la tarea puede limpiar y reintentar);
# el hard limit mata el proceso si el soft limit no basta.
SOFT_TIME_LIMIT_SECONDS = int(os.environ.get("TASK_SOFT_TIME_LIMIT_SECONDS", "240"))
HARD_TIME_LIMIT_SECONDS = int(os.environ.get("TASK_TIME_LIMIT_SECONDS", "300"))

# ACK tardío + Redis: si un worker muere SIN avisar (kill -9, fallo de máquina), el mensaje que estaba procesando
# vuelve a la cola pasado este tiempo. Debe superar el hard time limit; 10 min = 300 s de tarea + margen.
VISIBILITY_TIMEOUT_SECONDS = int(os.environ.get("TASK_VISIBILITY_TIMEOUT_SECONDS", "600"))

# Directorio donde la API deja el CSV subido y de donde lo lee el worker. En docker-compose es un volumen
# compartido por `api` y `worker`: el mensaje de la cola nunca lleva el contenido del fichero, solo su nombre.
UPLOAD_DIR = Path(os.environ.get("TASK_UPLOAD_DIR") or Path(tempfile.gettempdir()) / "brasaland-task-uploads")

# Nombre de la tarea (estable: es lo que se ve en Flower y en los logs).
ANALYZE_INCIDENTS_TASK = "incidents.analyze_csv"


def backoff_seconds(retries_done: int) -> int:
    """Segundos de espera antes del siguiente reintento (exponencial, con tope)."""
    return min(RETRY_BACKOFF_BASE_SECONDS * (2**retries_done), RETRY_BACKOFF_MAX_SECONDS)
