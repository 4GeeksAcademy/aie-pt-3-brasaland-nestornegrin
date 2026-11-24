"""Procesamiento asíncrono (ticket feature/async-processing): el email de «olvidé mi contraseña» (Resend, servicio externo)
sale del ciclo petición-respuesta y lo procesa un worker con reintentos, backoff, dead-letter queue e idempotencia.

No necesitan Redis ni un worker real: el almacén de idempotencia es el de memoria, el broker se sustituye por un doble y la
tarea se ejecuta con `.apply()` (síncrono, misma lógica de reintentos que en un worker). El proveedor se simula con un fallo.
"""
from __future__ import annotations

import logging
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.auth.models import UserRole
from services.async_tasks import config, contracts, dlq, email_tasks, idempotency, status
from services.async_tasks.email_tasks import send_password_reset
from services.async_tasks.enqueue import enqueue_password_reset_email

KEY = "password-reset:42"


@pytest.fixture(autouse=True)
def store():
    memory = idempotency.MemoryIdempotencyStore()
    idempotency.set_store(memory)
    yield memory
    idempotency.set_store(None)


@pytest.fixture
def dlq_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    dlq.set_engine(engine)
    yield engine
    dlq.set_engine(None)


@pytest.fixture
def provider(monkeypatch):
    """El «Resend» simulado: cuenta envíos y puede fallar las primeras N llamadas."""

    class Provider:
        def __init__(self):
            self.sent: list[tuple[str, str, str | None]] = []
            self.calls = 0
            self.fail_first = 0

        def __call__(self, to_email, token, idempotency_key=None):
            self.calls += 1
            if self.calls <= self.fail_first:
                raise ConnectionError("Resend caído (simulado)")
            self.sent.append((to_email, token, idempotency_key))

    fake = Provider()
    monkeypatch.setattr(email_tasks, "send_password_reset_email", fake)
    return fake


def run(key=KEY, to="ana@example.com", token="tok-secreto-123"):
    return send_password_reset.apply(kwargs={"idempotency_key": key, "sealed": contracts.seal(to, token)})


# ===================================================================== 1 · fuera del ciclo petición-respuesta
def test_la_peticion_solo_encola_y_responde_sin_llamar_al_proveedor(client, register_user, provider):
    register_user(email="ana@example.com", password="ValidPass123")
    published = []

    def fake_apply_async(args=None, kwargs=None, task_id=None, **_):
        published.append({"kwargs": kwargs, "task_id": task_id})

    with patch.object(send_password_reset, "apply_async", fake_apply_async):
        response = client.post("/auth/forgot-password", json={"email": "ana@example.com"})

    assert response.status_code == 200
    assert provider.calls == 0  # el proveedor NO se llamó dentro de la petición
    assert len(published) == 1  # …se encoló una tarea para el worker
    assert published[0]["kwargs"]["idempotency_key"].startswith("password-reset:")


def test_el_mensaje_de_la_cola_no_lleva_el_token_ni_el_correo_en_claro(client, register_user):
    register_user(email="ana@example.com", password="ValidPass123")
    published = []

    def fake_apply_async(args=None, kwargs=None, task_id=None, **_):
        published.append(kwargs)

    with patch.object(send_password_reset, "apply_async", fake_apply_async):
        client.post("/auth/forgot-password", json={"email": "ana@example.com"})

    assert set(published[0]) == {"idempotency_key", "sealed"}  # el contrato: nada más
    wire = str(published[0])
    assert "ana@example.com" not in wire and "token" not in contracts.seal("a@b.c", "t")
    to_email, token = contracts.unseal(published[0]["sealed"])  # el worker sí puede leerlo
    assert to_email == "ana@example.com" and len(token) > 20


def test_un_mensaje_manipulado_o_caducado_no_se_puede_leer(monkeypatch):
    sealed = contracts.seal("ana@example.com", "tok")
    with pytest.raises(contracts.InvalidMessage):
        contracts.unseal(sealed[:-4] + "AAAA")
    monkeypatch.setattr(contracts, "MAX_AGE_SECONDS", -1)
    with pytest.raises(contracts.InvalidMessage):
        contracts.unseal(sealed)


# ===================================================================== 2 · reintentos con backoff
def test_el_worker_envia_el_email_a_la_primera(provider):
    outcome = run()
    assert outcome.successful() and outcome.result == {"status": "sent", "attempts": 1}
    assert provider.sent == [("ana@example.com", "tok-secreto-123", KEY)]  # la clave viaja también al proveedor


def test_un_fallo_del_proveedor_dispara_reintentos_con_backoff_exponencial(provider, dlq_engine, monkeypatch):
    countdowns: list[int] = []
    real_retry = send_password_reset.retry

    def spy(*args, **kwargs):
        countdowns.append(kwargs["countdown"])
        return real_retry(*args, **kwargs)

    monkeypatch.setattr(send_password_reset, "retry", spy)
    monkeypatch.setattr(config, "RETRY_BACKOFF_BASE_SECONDS", 2)
    provider.fail_first = 2  # falla 2 veces y a la tercera responde
    outcome = run()

    assert outcome.successful() and outcome.result["attempts"] == 3
    assert countdowns == [2, 4]  # backoff: 2 s y luego 4 s, nunca inmediato
    assert len(provider.sent) == 1  # y el email salió UNA sola vez
    assert dlq.list_dead_letters() == []  # se recuperó: no es una tarea muerta


def test_el_log_de_cada_intento_queda_registrado(provider, dlq_engine, caplog):
    provider.fail_first = 1
    with caplog.at_level(logging.INFO, logger="brasaland.tasks"):
        run()
    text = caplog.text
    assert "status=retry" in text and "attempt=1" in text and "attempt=2" in text and "status=success" in text


# ===================================================================== 3 · dead-letter queue
def test_agotados_los_reintentos_la_tarea_cae_en_la_dlq_y_no_desaparece(provider, dlq_engine, monkeypatch):
    monkeypatch.setattr(config, "RETRY_BACKOFF_BASE_SECONDS", 0)
    provider.fail_first = 99  # el proveedor no se recupera
    outcome = run()

    assert outcome.failed()
    assert provider.calls == 4  # 1 intento + 3 reintentos, ni uno más
    (row,) = dlq.list_dead_letters()
    assert (row["task_id"], row["task_name"], row["attempt"]) == (outcome.id, config.SEND_PASSWORD_RESET_TASK, 4)
    assert "Resend caído" in row["error_message"] and row["failed_at"] is not None
    assert "tok-secreto-123" not in row["error_message"]  # la DLQ no guarda el token


def test_un_mensaje_caducado_va_directo_a_la_dlq_sin_gastar_reintentos(provider, dlq_engine, monkeypatch):
    monkeypatch.setattr(contracts, "MAX_AGE_SECONDS", -1)
    outcome = run()
    assert outcome.failed() and provider.calls == 0
    (row,) = dlq.list_dead_letters()
    assert row["attempt"] == 1 and "InvalidMessage" in row["error_message"]


def test_tras_fallar_definitivamente_se_libera_el_cerrojo(provider, dlq_engine, monkeypatch, store):
    monkeypatch.setattr(config, "RETRY_BACKOFF_BASE_SECONDS", 0)
    provider.fail_first = 99
    run()
    assert store.begin(KEY) == "acquired"  # no queda bloqueada para siempre


# ===================================================================== 4 · idempotencia
def test_encolar_dos_veces_con_la_misma_clave_publica_una_sola_vez(store):
    published = []

    def fake_apply_async(args=None, kwargs=None, task_id=None, **_):
        published.append(task_id)

    with patch.object(send_password_reset, "apply_async", fake_apply_async):
        first = enqueue_password_reset_email("ana@example.com", "tok", KEY)
        second = enqueue_password_reset_email("ana@example.com", "tok", KEY)
        other = enqueue_password_reset_email("ana@example.com", "tok", "password-reset:43")

    assert first == second and len(published) == 2  # la misma clave NO vuelve a la cola
    assert other != first  # otra operación distinta sí
    assert str(uuid.UUID(first)) == first


def test_ejecutar_dos_veces_la_misma_clave_no_envia_el_email_dos_veces(provider):
    """PRUEBA DE IDEMPOTENCIA: el broker entrega el mismo mensaje dos veces (ACK tardío, visibility timeout)."""
    first = run()
    second = run()  # misma clave, mismo mensaje
    assert first.result["status"] == "sent"
    assert second.successful() and second.result["status"] == "duplicate_skipped"
    assert len(provider.sent) == 1  # el efecto ocurrió UNA vez


def test_una_clave_distinta_si_envia(provider):
    run(key="password-reset:1")
    run(key="password-reset:2")
    assert len(provider.sent) == 2


def test_si_la_misma_operacion_esta_en_curso_en_otro_worker_se_reintenta_sin_enviar(provider, store, dlq_engine, monkeypatch):
    monkeypatch.setattr(config, "RETRY_BACKOFF_BASE_SECONDS", 0)
    store.begin(KEY)  # otro worker la tiene
    outcome = run()
    assert outcome.failed() and provider.calls == 0  # nunca se pisó con un envío concurrente


def test_un_fallo_encolando_libera_la_clave_para_poder_reintentar(store):
    with patch.object(send_password_reset, "apply_async", side_effect=ConnectionError("Redis caído")):
        with pytest.raises(ConnectionError):
            enqueue_password_reset_email("ana@example.com", "tok", KEY)
    assert store.claim_enqueue(KEY, "x") is None  # la clave quedó libre


def test_resend_recibe_la_clave_de_idempotencia():
    from app.auth import email as email_module

    with patch("app.auth.email.resend") as mock_resend, patch.object(email_module, "RESEND_API_KEY", "re_fake"):
        email_module.send_password_reset_email("a@b.co", "tok", idempotency_key="password-reset:7")
    assert mock_resend.Emails.send.call_args[0][1] == {"idempotency_key": "password-reset:7"}


# ===================================================================== 5 · estado consultable
def test_el_estado_incluye_los_intentos(client, auth_headers, store, monkeypatch):
    headers = auth_headers()
    task_id = str(uuid.uuid4())
    store.record_attempt(task_id, 3)
    monkeypatch.setattr(status, "AsyncResult", lambda tid, app=None: type("R", (), {"state": "RETRY", "result": None})())
    body = client.get(f"/tasks/{task_id}", headers=headers).json()
    assert body["status"] == "started" and body["attempts"] == 3


def test_el_resultado_de_una_tarea_enviada_dice_cuantos_intentos_necesito(provider, dlq_engine, monkeypatch):
    monkeypatch.setattr(config, "RETRY_BACKOFF_BASE_SECONDS", 0)
    provider.fail_first = 2
    outcome = run()
    assert outcome.result == {"status": "sent", "attempts": 3}
    assert idempotency.get_store().attempts(outcome.id) == 3  # consultable también por task_id


def test_la_dlq_la_ve_un_admin_y_nadie_mas(client, auth_headers, dlq_engine):
    dlq.record_dead_letter("t-1", config.SEND_PASSWORD_RESET_TASK, 4, "ConnectionError: Resend caído")
    admin_headers = auth_headers("admin@example.com")
    main_module.user_repository._database.update({"role": UserRole.ADMIN.value}, doc_ids=[main_module.user_repository.get_by_email("admin@example.com").id])
    rows = client.get("/tasks/dead-letters", headers=admin_headers).json()
    assert [(r["task_id"], r["attempt"]) for r in rows] == [("t-1", 4)]
    assert client.get("/tasks/dead-letters", headers=auth_headers("user@example.com")).status_code == 403
    assert client.get("/tasks/dead-letters").status_code == 401
