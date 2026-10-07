import logging
from uuid import uuid4


def _event(event_type="incident_created", **extra):
    return {
        "eventId": str(uuid4()),
        "timestamp": "2026-10-07T10:00:00.000Z",
        "sessionId": str(uuid4()),
        "userId": "1",
        "event_type": event_type,
        "schemaVersion": "1.1.0",
        "requestId": str(uuid4()),
        "source": "frontend",
        "properties": {"category": "service"},
        **extra,
    }


def test_receives_batch_and_logs(client, caplog):
    with caplog.at_level(logging.INFO, logger="telemetry"):
        response = client.post(
            "/telemetry/events",
            json={"events": [_event("incident_created"), _event("page_viewed")]},
        )
    assert response.status_code == 200
    assert response.json() == {"received": 2}
    text = caplog.text
    assert "2 events" in text and "incident_created" in text and "page_viewed" in text


def test_empty_batch_ok(client):
    response = client.post("/telemetry/events", json={"events": []})
    assert response.status_code == 200
    assert response.json() == {"received": 0}


def test_invalid_envelope_rejected(client):
    bad = _event()
    del bad["eventId"]
    response = client.post("/telemetry/events", json={"events": [bad]})
    assert response.status_code == 400
