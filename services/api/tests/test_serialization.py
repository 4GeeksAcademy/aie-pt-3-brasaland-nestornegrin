"""Contrato de serialización: forma exacta de las respuestas y ausencia de
campos internos. Complementa los tests por endpoint de auth."""

from fastapi.routing import APIRoute

import app.main as main_module
from app.auth.models import UserUpdate

# Nombres que nunca deben aparecer en el esquema de salida de ningún endpoint.
FORBIDDEN_OUTPUT_FIELDS = {"hashed_password", "password", "token_hash", "new_password", "current_password"}


def _admin_headers(client, register_user):
    user = register_user(email="admin@example.com")
    main_module.user_repository._database.update({"role": "admin"}, doc_ids=[user["id"]])
    login = client.post("/auth/login", json={"email": "admin@example.com", "password": "ValidPass123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, user


def test_me_profile_does_not_expose_storage_keys(client, register_user, auth_headers):
    headers = auth_headers(email="shape@example.com")

    body = client.get("/auth/me", headers=headers).json()

    assert set(body) == {"email", "role", "profile"}
    assert set(body["profile"]) == {"name", "phone", "address"}


def test_profiles_me_get_and_put_return_the_public_projection(client, auth_headers):
    headers = auth_headers(email="profile-shape@example.com")

    got = client.get("/profiles/me", headers=headers)
    updated = client.put("/profiles/me", headers=headers, json={"name": "Nuevo"})

    assert set(got.json()) == {"name", "phone", "address"}
    assert set(updated.json()) == {"name", "phone", "address"}
    assert updated.json()["name"] == "Nuevo"


def test_users_list_uses_the_lightweight_item_shape(client, register_user):
    headers, _ = _admin_headers(client, register_user)

    rows = client.get("/users", headers=headers).json()

    assert rows and all(set(row) == {"id", "email", "role", "is_active"} for row in rows)


def test_user_detail_keeps_the_safe_account_fields(client, register_user):
    headers, admin = _admin_headers(client, register_user)

    body = client.get(f"/users/{admin['id']}", headers=headers).json()

    assert set(body) == {"id", "email", "is_active", "role", "created_at"}


def test_a_regular_user_cannot_toggle_is_active(client, register_user, auth_headers):
    headers = auth_headers(email="toggle@example.com")
    user_id = main_module.user_repository.get_by_email("toggle@example.com").id

    response = client.put(f"/users/{user_id}", headers=headers, json={"is_active": False})

    assert response.status_code == 403
    assert main_module.user_repository.get(user_id).is_active is True


def test_login_without_any_identifier_is_rejected(client):
    response = client.post("/auth/login", json={"password": "ValidPass123"})

    assert response.status_code == 400


def test_supplier_responses_use_the_explicit_schema(client, auth_headers):
    headers = auth_headers(email="suppliers@example.com")
    expected = {"id", "name", "categories", "country", "rate", "status", "updated_at"}

    listing = client.get("/api/suppliers", headers=headers)
    detail = client.get(f"/api/suppliers/{listing.json()[0]['id']}", headers=headers)

    assert listing.status_code == 200 and detail.status_code == 200
    assert all(set(row) == expected for row in listing.json())
    assert set(detail.json()) == expected


def test_incident_list_is_lighter_than_incident_detail(client, auth_headers):
    headers = auth_headers(email="incidents@example.com")
    created = client.post(
        "/api/incidents",
        headers=headers,
        json={
            "title": "Nevera averiada",
            "description": "La nevera de la cocina dejó de enfriar.",
            "category": "Queja",
            "origin": "branch",
            "branch": "central",
        },
    )
    assert created.status_code == 201, created.text

    listing = client.get("/api/incidents", headers=headers).json()
    detail = client.get(f"/api/incidents/{created.json()['id']}", headers=headers).json()

    assert set(listing[0]) == {"id", "title", "category", "origin", "branch", "status"}
    assert set(detail) == {"id", "title", "description", "category", "origin", "branch", "status", "created_at", "updated_at"}


def test_analyze_returns_the_typed_analysis_payload(client, auth_headers):
    headers = auth_headers(email="analyze@example.com")
    csv_bytes = "id,category,status\n".encode()

    response = client.post("/api/incidents/analyze", headers=headers, files={"file": ("x.csv", csv_bytes, "text/csv")})

    # Con un CSV sin columnas válidas la API responde 400 con detalle, nunca un dict ad hoc.
    assert response.status_code in (200, 400)
    if response.status_code == 200:
        assert set(response.json()) == {
            "total_processed", "valid_records", "invalid_records", "by_category",
            "by_status", "average_closed_satisfaction", "invalid_reasons",
        }


def test_every_json_endpoint_declares_a_response_schema():
    """Ninguna ruta devuelve un objeto sin esquema: salvo borrados (204) y la
    descarga CSV, todas las respuestas 2xx declaran contenido tipado."""
    for path, methods in main_module.app.openapi()["paths"].items():
        for method, operation in methods.items():
            for code, response in operation["responses"].items():
                if not code.startswith("2") or code == "204":
                    continue
                content = response.get("content", {})
                if "text/csv" in content:
                    continue
                schema = content.get("application/json", {}).get("schema", {})
                # Un esquema tipado es una referencia a un modelo o una lista
                # de ellos; un {"type": "object"} suelto es un dict sin contrato.
                assert "$ref" in schema or "$ref" in schema.get("items", {}), (
                    f"{method.upper()} {path} no declara un esquema de respuesta"
                )


def test_no_output_schema_exposes_credential_fields():
    schemas = main_module.app.openapi()["components"]["schemas"]
    inputs = {"UserCreate", "LoginRequest", "ResetPasswordRequest", "ChangePasswordRequest"}
    for name, schema in schemas.items():
        if name in inputs or name.endswith("Request") or name.endswith("Create") or name.endswith("Update"):
            continue
        leaked = FORBIDDEN_OUTPUT_FIELDS & set(schema.get("properties", {}))
        assert not leaked, f"{name} expone {leaked}"


def _api_routes(routes):
    """Recorre las rutas, incluidas las de los routers montados con include_router."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from _api_routes(inner.routes)
        elif isinstance(route, APIRoute):
            yield route


def test_every_route_declares_an_explicit_response_model_or_has_no_body():
    """Cada operación declara response_model; las únicas excepciones son las
    que no devuelven JSON: borrados (204, sin cuerpo) y la descarga CSV."""
    without_model = []
    for route in _api_routes(main_module.app.routes):
        if route.response_model is None:
            without_model.append((route.status_code, route.path))
    assert without_model, "se esperaban los borrados 204 y la exportación CSV"
    for status_code, path in without_model:
        assert status_code == 204 or path == "/api/incidents/results/export", (
            f"{path} no declara response_model"
        )
