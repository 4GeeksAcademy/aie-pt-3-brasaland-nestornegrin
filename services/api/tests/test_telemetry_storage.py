"""Endpoint real de telemetría: parseo por evento, rechazos individuales y bulk insert."""
import json
import logging
from uuid import uuid4

import pytest
from sqlalchemy import event as sa_event, select, text
from sqlmodel import Session

from app.database import engine
from app.telemetry.orm import TelemetryEventRecord


@pytest.fixture(autouse=True)
def _clean_telemetry_table():
    # En Postgres la migración bloquea DELETE (tabla inmutable): se limpia con TRUNCATE.
    with Session(engine) as session:
        if engine.dialect.name == "postgresql":
            session.execute(text("TRUNCATE telemetry_events"))
        else:
            session.execute(text("DELETE FROM telemetry_events"))
        session.commit()
    yield


def _event(event_type="incident_created", properties=None, **overrides):
    base = {
        "eventId": str(uuid4()),
        "timestamp": "2026-10-07T10:00:00.000Z",
        "sessionId": str(uuid4()),
        "userId": "1",
        "event_type": event_type,
        "schemaVersion": "1.1.0",
        "requestId": str(uuid4()),
        "source": "frontend",
        "properties": properties
        if properties is not None
        else {"incidentId": 4, "category": "Queja", "origin": "branch", "branch": "Brasaland Laureles"},
    }
    base.update(overrides)
    return base


def _rows():
    with Session(engine) as session:
        return list(session.scalars(select(TelemetryEventRecord).order_by(TelemetryEventRecord.id)))


def test_stores_valid_events_with_correct_columns(client):
    outbound = _event(
        "outbound_order_created",
        {"exitId": 9, "ingredientId": 3, "restaurant": "Brasaland El Poblado", "quantity": 2.5,
         "stockBefore": 20, "stockAfter": 17.5, "reasonProvided": False},
    )
    response = client.post("/telemetry/events", json={"events": [_event(), outbound]})
    assert response.status_code == 200
    assert response.json() == {"received": 2, "stored": 2, "rejected": 0}

    rows = _rows()
    assert [r.event_type for r in rows] == ["incident_created", "outbound_order_created"]
    first = rows[0]
    assert first.service == "frontend"
    assert first.user_id == "1"
    assert first.timestamp.year == 2026 and first.timestamp.month == 10
    # tags conserva las dimensiones del dominio (sede / restaurante)
    assert first.tags["branch"] == "Brasaland Laureles"
    assert rows[1].tags["restaurant"] == "Brasaland El Poblado"


def test_mixed_batch_persists_valid_and_counts_rejected(client):
    no_event_id = _event()
    del no_event_id["eventId"]
    batch = [
        _event(),
        no_event_id,                                    # envelope inválido
        _event("evento_inventado", {"x": 1}),            # tipo fuera del plan
        _event("incident_created", {"incidentId": 1}),   # faltan propiedades obligatorias
        "no soy un objeto",                              # ni siquiera es un dict
        _event(),
    ]
    response = client.post("/telemetry/events", json={"events": batch})
    assert response.status_code == 200
    assert response.json() == {"received": 6, "stored": 2, "rejected": 4}
    assert len(_rows()) == 2


def test_tags_keep_only_allowlisted_keys(client):
    props = {"incidentId": 4, "category": "Queja", "origin": "branch", "branch": "central", "email": "a@b.com"}
    response = client.post("/telemetry/events", json={"events": [_event(properties=props)]})
    assert response.json() == {"received": 1, "stored": 1, "rejected": 0}
    assert "email" not in _rows()[0].tags


def test_duplicate_event_id_is_not_stored_twice(client):
    event = _event()
    assert client.post("/telemetry/events", json={"events": [event]}).json()["stored"] == 1
    again = client.post("/telemetry/events", json={"events": [event]}).json()
    assert again == {"received": 1, "stored": 0, "rejected": 1}
    assert len(_rows()) == 1


def test_batch_is_one_insert_statement(client):
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if "INSERT INTO telemetry_events" in statement:
            statements.append(statement)

    sa_event.listen(engine, "before_cursor_execute", capture)
    try:
        client.post("/telemetry/events", json={"events": [_event() for _ in range(20)]})
    finally:
        sa_event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    assert len(_rows()) == 20


def test_accepts_text_plain_body(client):
    # sendBeacon/fetch del frontend usan text/plain para evitar el preflight de CORS.
    response = client.post(
        "/telemetry/events",
        content=json.dumps({"events": [_event()]}),
        headers={"Content-Type": "text/plain;charset=UTF-8"},
    )
    assert response.status_code == 200
    assert response.json()["stored"] == 1


def test_empty_batch_ok(client):
    assert client.post("/telemetry/events", json={"events": []}).json() == {"received": 0, "stored": 0, "rejected": 0}


@pytest.mark.parametrize("body", ["not json", json.dumps({"foo": 1}), json.dumps({"events": "x"}), json.dumps([1])])
def test_unparseable_envelope_is_400(client, body):
    response = client.post("/telemetry/events", content=body, headers={"Content-Type": "text/plain"})
    assert response.status_code == 400


def test_oversized_batch_is_413(client):
    response = client.post("/telemetry/events", json={"events": [{}] * 501})
    assert response.status_code == 413


def test_logs_batch_summary(client, caplog):
    with caplog.at_level(logging.INFO, logger="telemetry"):
        client.post("/telemetry/events", json={"events": [_event()]})
    assert "received=1 stored=1 rejected=0" in caplog.text
