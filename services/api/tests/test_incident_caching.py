"""Caché de lectura de incidencias: aciertos, invalidación en escrituras y
que nunca se sirve a quien no tiene sesión."""

INCIDENT = {
    "title": "Caché: nevera averiada",
    "description": "Texto de prueba",
    "category": "Queja",
    "origin": "branch",
    "branch": "central",
}


def _create(client, headers, **overrides):
    response = client.post("/api/incidents", headers=headers, json={**INCIDENT, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def test_summary_is_cached_until_an_incident_is_created(client, auth_headers):
    headers = auth_headers(email="cache-summary@example.com")
    _create(client, headers)  # la escritura invalida: la primera lectura es un fallo

    first = client.get("/api/incidents/summary", headers=headers)
    second = client.get("/api/incidents/summary", headers=headers)

    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"
    assert second.json() == first.json()

    _create(client, headers)
    after_write = client.get("/api/incidents/summary", headers=headers)

    assert after_write.headers["X-Cache"] == "MISS"
    assert after_write.json()["total"] == first.json()["total"] + 1


def test_list_cache_is_keyed_by_filters(client, auth_headers):
    headers = auth_headers(email="cache-filters@example.com")
    _create(client, headers)

    open_first = client.get("/api/incidents?status=open", headers=headers)
    open_second = client.get("/api/incidents?status=open", headers=headers)
    other_filter = client.get("/api/incidents?status=resolved", headers=headers)

    assert open_first.headers["X-Cache"] == "MISS"
    assert open_second.headers["X-Cache"] == "HIT"
    assert other_filter.headers["X-Cache"] == "MISS"  # otra clave, no reutiliza la anterior
    assert open_second.json() == open_first.json()


def test_changing_a_status_invalidates_the_filtered_list(client, auth_headers):
    headers = auth_headers(email="cache-status@example.com")
    incident = _create(client, headers)
    before = client.get("/api/incidents?status=open", headers=headers)
    assert client.get("/api/incidents?status=open", headers=headers).headers["X-Cache"] == "HIT"
    assert incident["id"] in [row["id"] for row in before.json()]

    patched = client.patch(f"/api/incidents/{incident['id']}/status", headers=headers, json={"status": "in_progress"})
    assert patched.status_code == 200

    after = client.get("/api/incidents?status=open", headers=headers)
    assert after.headers["X-Cache"] == "MISS"
    assert incident["id"] not in [row["id"] for row in after.json()]  # ya no aparece como abierta


def test_cached_responses_are_never_served_without_a_session(client, auth_headers):
    headers = auth_headers(email="cache-auth@example.com")
    _create(client, headers)
    client.get("/api/incidents", headers=headers)
    client.get("/api/incidents/summary", headers=headers)  # caché caliente

    list_response = client.get("/api/incidents")
    summary_response = client.get("/api/incidents/summary")

    assert list_response.status_code == 401
    assert summary_response.status_code == 401
    assert "X-Cache" not in list_response.headers and "X-Cache" not in summary_response.headers


def test_a_no_op_status_change_does_not_throw_away_the_cache(client, auth_headers):
    headers = auth_headers(email="cache-noop@example.com")
    incident = _create(client, headers)
    client.get("/api/incidents/summary", headers=headers)

    same_status = client.patch(f"/api/incidents/{incident['id']}/status", headers=headers, json={"status": "open"})

    assert same_status.status_code == 200
    assert client.get("/api/incidents/summary", headers=headers).headers["X-Cache"] == "HIT"
