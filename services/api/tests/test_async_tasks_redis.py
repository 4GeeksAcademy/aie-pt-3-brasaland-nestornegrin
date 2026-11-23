"""DEV-55 · Prueba de integración con un Redis REAL (opt-in: se salta si no hay `redis-server` instalado).

Levanta un `redis-server` temporal en un puerto libre y un worker de Celery en un hilo (`start_worker`), y
comprueba de punta a punta lo que el ticket evalúa: la tarea viaja por Redis, el worker la ejecuta aparte,
`GET /tasks/{id}` refleja el estado, y una tarea que siempre falla acaba en la DLQ con backoff.
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import threading
import time

import pytest
from celery.contrib.testing.worker import start_worker
from celery.result import AsyncResult
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from services.async_tasks import config, dlq, results, staging
from services.async_tasks.incident_tasks import analyze_incidents_csv
from services.celery_app import celery_app

pytestmark = [
    pytest.mark.skipif(shutil.which("redis-server") is None, reason="redis-server no está instalado"),
    # Al apagar el Redis temporal, el consumidor de resultados de Celery avisa de la reconexión fallida al limpiarse.
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]


def _rebind_celery(url: str) -> None:
    """Apunta la instancia compartida de Celery a otro Redis. Celery cachea el result backend y el pool del
    broker la primera vez que se usan (p. ej. en otros módulos de tests), así que cambiar `conf` no basta."""
    celery_app.conf.update(broker_url=url, result_backend=url)
    celery_app._backend_cache = None
    celery_app._local = threading.local()
    celery_app._pool = None
    celery_app.__dict__.pop("amqp", None)  # propiedad cacheada que guarda el pool de productores del broker


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def redis_url():
    port = _free_port()
    process = subprocess.Popen(
        ["redis-server", "--port", str(port), "--save", "", "--appendonly", "no", "--maxmemory-policy", "noeviction"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"redis://127.0.0.1:{port}/0"
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield url
    process.terminate()
    process.wait(timeout=10)


@pytest.fixture(scope="module")
def worker(redis_url, tmp_path_factory):
    upload_dir = tmp_path_factory.mktemp("uploads")
    saved = (config.UPLOAD_DIR, config.RETRY_BACKOFF_BASE_SECONDS, config.REDIS_URL)
    config.UPLOAD_DIR, config.RETRY_BACKOFF_BASE_SECONDS, config.REDIS_URL = upload_dir, 1, redis_url
    _rebind_celery(redis_url)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    dlq.set_engine(engine)
    with start_worker(celery_app, perform_ping_check=False, loglevel="WARNING", pool="solo"):
        yield
    dlq.set_engine(None)
    try:  # cierra la suscripción de resultados antes de que se apague el Redis temporal
        celery_app.backend.result_consumer.stop()
    except Exception:  # noqa: BLE001 - solo limpieza de test
        pass
    config.UPLOAD_DIR, config.RETRY_BACKOFF_BASE_SECONDS, config.REDIS_URL = saved
    _rebind_celery(saved[2])


def _wait(task_id: str, timeout: float = 30):
    result = AsyncResult(task_id, app=celery_app)
    deadline = time.time() + timeout
    while time.time() < deadline and result.state not in ("SUCCESS", "FAILURE"):
        time.sleep(0.1)
    return result


def test_task_runs_in_a_worker_through_real_redis(worker, redis_url):
    csv_text = (
        "incident_id,customer_name,customer_email,category,status,created_at\n"
        "1,Ana,ana@example.com,Queja,Abierto,2026-01-01\n"
        "2,Luis,luis@example.com,Solicitud,Cerrado,2026-01-02\n"
    )
    upload_id = staging.stage_upload(csv_text.encode())
    started = time.perf_counter()
    task = analyze_incidents_csv.delay(upload_id)
    enqueue_ms = (time.perf_counter() - started) * 1000

    result = _wait(task.id)
    assert result.state == "SUCCESS"
    assert result.result["total_processed"] == 2
    assert enqueue_ms < 200  # encolar no espera a que la tarea termine
    assert results.load_latest()["total_processed"] == 2  # el export lee de Redis, no de memoria de la API


def test_failing_task_is_retried_with_backoff_and_dead_lettered_through_real_redis(worker):
    upload_id = staging.stage_upload(b"x,y\n1,2\n")
    started = time.perf_counter()
    task = analyze_incidents_csv.delay(upload_id)

    result = _wait(task.id, timeout=60)
    elapsed = time.perf_counter() - started

    assert result.state == "FAILURE"
    # Backoff 1 s + 2 s + 4 s entre las 4 ejecuciones: no hay reintentos inmediatos.
    assert elapsed >= 7
    rows = [row for row in dlq.list_dead_letters() if row["task_id"] == task.id]
    assert len(rows) == 1 and rows[0]["attempt"] == 4
    assert "Faltan columnas obligatorias" in rows[0]["error_message"]
