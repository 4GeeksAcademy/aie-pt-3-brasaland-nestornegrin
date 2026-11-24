"""DEV-55 · Cola de tareas asíncronas (Celery + Redis).

No necesitan Redis ni un worker: el publicador y el result backend se sustituyen por dobles, y la tarea se
ejecuta en modo `apply()` (síncrono, misma lógica de reintentos). La prueba con Redis y un worker reales es
`test_async_tasks_redis.py` (opt-in: solo si hay un `redis-server` instalado).
"""
from __future__ import annotations

import csv
import io
import uuid
from types import SimpleNamespace

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

import app.main as main_module
from services.async_tasks import config, dlq, results, staging, status
from services.async_tasks.incident_tasks import analyze_incidents_csv

@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    return config.UPLOAD_DIR


@pytest.fixture
def dlq_engine():
    """DLQ sobre SQLite en memoria (misma tabla, mismo código que en Postgres)."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    dlq.set_engine(engine)
    yield engine
    dlq.set_engine(None)


@pytest.fixture
def sample_csv() -> bytes:
    """Un CSV real y válido para el analizador (cabecera + 2 filas)."""
    from packages.shared.incident_validation import ALLOWED_CATEGORIES, ALLOWED_CSV_STATUSES, REQUIRED_CSV_FIELDS

    buffer = io.StringIO(newline="")
    fields = list(REQUIRED_CSV_FIELDS)
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for index in range(2):
        row = {field: f"valor {index}" for field in fields}
        row["category"] = ALLOWED_CATEGORIES[0]
        row["status"] = ALLOWED_CSV_STATUSES[0]
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


# --------------------------------------------------------------------------- #
# Reintentos y backoff
# --------------------------------------------------------------------------- #
def test_backoff_is_exponential_and_capped(monkeypatch):
    monkeypatch.setattr(config, "RETRY_BACKOFF_BASE_SECONDS", 2)
    monkeypatch.setattr(config, "RETRY_BACKOFF_MAX_SECONDS", 10)
    assert [config.backoff_seconds(n) for n in range(5)] == [2, 4, 8, 10, 10]


def test_task_is_configured_with_three_retries_and_timeouts():
    assert analyze_incidents_csv.max_retries == 3
    assert analyze_incidents_csv.soft_time_limit and analyze_incidents_csv.time_limit
    assert analyze_incidents_csv.soft_time_limit < analyze_incidents_csv.time_limit
    assert analyze_incidents_csv.acks_late is True


def test_failing_task_retries_with_increasing_countdown_then_goes_to_dlq(upload_dir, dlq_engine, monkeypatch):
    """Un CSV sin cabecera válida falla siempre: 1 intento + 3 reintentos, backoff 2·4·8 s, y a la DLQ."""
    countdowns: list[int] = []
    real_retry = analyze_incidents_csv.retry

    def spy_retry(*args, **kwargs):
        countdowns.append(kwargs["countdown"])
        return real_retry(*args, **kwargs)

    monkeypatch.setattr(analyze_incidents_csv, "retry", spy_retry)
    monkeypatch.setattr(config, "RETRY_BACKOFF_BASE_SECONDS", 2)
    upload_id = staging.stage_upload(b"esto,no,es,un,csv,de,incidencias\n1,2,3,4,5,6,7\n")

    outcome = analyze_incidents_csv.apply(args=[upload_id])

    assert outcome.failed()
    # Backoff exponencial: nunca se reintenta de inmediato. Las 3 primeras llamadas programan un reintento
    # (2 s, 4 s, 8 s); la cuarta ya no tiene reintentos que gastar: Celery relanza el error y esa ejecución es la última.
    assert countdowns[:3] == [2, 4, 8]
    assert len(countdowns) == 4
    rows = dlq.list_dead_letters()
    assert len(rows) == 1
    assert rows[0]["task_id"] == outcome.id
    assert rows[0]["task_name"] == config.ANALYZE_INCIDENTS_TASK
    assert rows[0]["attempt"] == 4  # el intento inicial + 3 reintentos
    assert "Faltan columnas obligatorias" in rows[0]["error_message"]
    assert rows[0]["failed_at"] is not None
    assert not (upload_dir / upload_id).exists()  # fichero aparcado limpiado tras el fallo definitivo


def test_task_that_succeeds_after_a_failure_is_not_dead_lettered(upload_dir, dlq_engine, monkeypatch, sample_csv):
    stored: list[dict] = []
    monkeypatch.setattr(results, "store_latest", stored.append)
    upload_id = staging.stage_upload(sample_csv)
    real_read = staging.read_upload_text
    calls = {"n": 0}

    def flaky_read(upload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("fallo transitorio de disco")
        return real_read(upload)

    monkeypatch.setattr(staging, "read_upload_text", flaky_read)
    outcome = analyze_incidents_csv.apply(args=[upload_id])

    assert outcome.successful()
    assert calls["n"] == 2
    assert outcome.result["total_processed"] == 2
    assert stored and stored[0]["total_processed"] == 2
    assert dlq.list_dead_letters() == []
    assert not (upload_dir / upload_id).exists()  # limpiado tras el éxito


def test_dlq_failure_never_breaks_failure_handling(monkeypatch, caplog):
    def boom():
        raise RuntimeError("base de datos caída")

    monkeypatch.setattr(dlq, "get_engine", boom)
    dlq.record_dead_letter("abc", "t", 4, "error")  # no lanza
    assert "NO se pudo registrar" in caplog.text


# --------------------------------------------------------------------------- #
# El mensaje de la cola es ligero
# --------------------------------------------------------------------------- #
def test_staging_roundtrip_and_path_traversal_is_rejected(upload_dir):
    upload_id = staging.stage_upload("a,b\n1,2\n".encode("utf-8"))
    assert upload_id.endswith(".csv") and len(upload_id) == 36
    assert staging.read_upload_text(upload_id) == "a,b\n1,2\n"
    staging.delete_upload(upload_id)
    assert not (upload_dir / upload_id).exists()
    for hostile in ("../../etc/passwd", "/etc/passwd", "x.csv", f"{uuid.uuid4().hex}.csv/../x"):
        with pytest.raises(ValueError):
            staging.read_upload_text(hostile)
    staging.delete_upload("../../etc/passwd")  # no lanza ni borra nada


# --------------------------------------------------------------------------- #
# POST /api/incidents/analyze → 202
# --------------------------------------------------------------------------- #
def test_analyze_returns_202_with_task_id_and_enqueues_only_an_identifier(client, auth_headers, upload_dir, monkeypatch, sample_csv):
    sent: list[tuple] = []

    def fake_delay(*args, **kwargs):
        sent.append((args, kwargs))
        return SimpleNamespace(id=str(uuid.uuid4()))

    monkeypatch.setattr(main_module.analyze_incidents_csv, "delay", fake_delay)
    response = client.post("/api/incidents/analyze", files={"file": ("incidents.csv", sample_csv, "text/csv")}, headers=auth_headers())

    assert response.status_code == 202
    assert list(response.json()) == ["task_id"]
    uuid.UUID(response.json()["task_id"])
    (args, kwargs), = sent
    assert kwargs == {} and len(args) == 1
    assert isinstance(args[0], str) and len(args[0]) == 36  # solo el id del fichero…
    assert len(args[0]) < len(sample_csv)  # …nunca el contenido
    assert (upload_dir / args[0]).read_bytes() == sample_csv  # el CSV está aparcado para el worker


@pytest.mark.parametrize(
    ("name", "content", "status_code"),
    [("incidents.txt", b"a,b\n", 415), ("incidents.csv", b"", 400)],
)
def test_analyze_still_validates_extension_and_empty_file_synchronously(client, auth_headers, upload_dir, name, content, status_code):
    response = client.post("/api/incidents/analyze", files={"file": (name, content, "text/csv")}, headers=auth_headers())
    assert response.status_code == status_code
    assert not upload_dir.exists() or not list(upload_dir.iterdir())  # nada aparcado ni encolado


def test_analyze_requires_authentication(client):
    assert client.post("/api/incidents/analyze", files={"file": ("a.csv", b"x", "text/csv")}).status_code == 401


def test_analyze_responds_503_and_cleans_up_when_the_queue_is_down(client, auth_headers, upload_dir, monkeypatch, sample_csv):
    def down(*_args, **_kwargs):
        raise RedisConnectionError("redis caído")

    monkeypatch.setattr(main_module.analyze_incidents_csv, "delay", down)
    response = client.post("/api/incidents/analyze", files={"file": ("a.csv", sample_csv, "text/csv")}, headers=auth_headers())
    assert response.status_code == 503
    assert not list(upload_dir.iterdir())  # sin tarea no queda fichero huérfano


# --------------------------------------------------------------------------- #
# GET /tasks/{task_id}
# --------------------------------------------------------------------------- #
class _FakeAsyncResult:
    def __init__(self, state, result=None):
        self.state, self.result = state, result


@pytest.mark.parametrize(
    ("celery_state", "api_status"),
    [("PENDING", "pending"), ("RECEIVED", "pending"), ("STARTED", "started"), ("RETRY", "started"), ("SUCCESS", "success"), ("FAILURE", "failure")],
)
def test_task_status_maps_every_celery_state(client, auth_headers, monkeypatch, celery_state, api_status):
    payload = {"total_processed": 2}
    result = {"SUCCESS": payload, "FAILURE": ValueError("cabecera inválida")}.get(celery_state)
    monkeypatch.setattr(status, "AsyncResult", lambda task_id, app=None: _FakeAsyncResult(celery_state, result))
    task_id = str(uuid.uuid4())
    response = client.get(f"/tasks/{task_id}", headers=auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == task_id and body["status"] == api_status
    if api_status == "success":
        assert body["result"] == payload
    elif api_status == "failure":
        assert body["result"] == {"error": "ValueError: cabecera inválida"}
    else:
        assert body["result"] is None


def test_task_status_rejects_malformed_ids_and_requires_auth(client, auth_headers):
    assert client.get("/tasks/no-es-un-uuid", headers=auth_headers()).status_code == 404
    assert client.get(f"/tasks/{uuid.uuid4()}").status_code == 401


def test_task_status_responds_503_when_redis_is_down(client, auth_headers, monkeypatch):
    def down(*_args, **_kwargs):
        raise RedisConnectionError("redis caído")

    monkeypatch.setattr(status, "AsyncResult", down)
    assert client.get(f"/tasks/{uuid.uuid4()}", headers=auth_headers()).status_code == 503


# --------------------------------------------------------------------------- #
# GET /api/incidents/results/export (el resultado ya no vive en memoria de la API)
# --------------------------------------------------------------------------- #
def test_export_reads_the_latest_result_stored_by_the_worker(client, auth_headers, monkeypatch):
    payload = {
        "total_processed": 3, "valid_records": 2, "invalid_records": 1,
        "by_category": {"Producto": 2}, "by_status": {"Cerrado": 2},
        "average_closed_satisfaction": 4.5, "invalid_reasons": {"x": 1},
    }
    monkeypatch.setattr(results, "load_latest", lambda: payload)
    response = client.get("/api/incidents/results/export", headers=auth_headers())
    assert response.status_code == 200
    assert "total_processed,,3" in response.text and "average_closed_satisfaction,,4.50" in response.text


def test_export_404_without_any_result_and_503_when_redis_is_down(client, auth_headers, monkeypatch):
    headers = auth_headers()  # registra el usuario una sola vez
    monkeypatch.setattr(results, "load_latest", lambda: None)
    assert client.get("/api/incidents/results/export", headers=headers).status_code == 404

    def down():
        raise RedisConnectionError("redis caído")

    monkeypatch.setattr(results, "load_latest", down)
    assert client.get("/api/incidents/results/export", headers=headers).status_code == 503


def test_dlq_table_matches_the_documented_columns(dlq_engine):
    dlq.record_dead_letter("t-1", "demo", 4, "Boom: x")
    with dlq_engine.connect() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(task_dead_letters)"))}
    assert columns == {"id", "task_id", "task_name", "attempt", "error_message", "failed_at"}
