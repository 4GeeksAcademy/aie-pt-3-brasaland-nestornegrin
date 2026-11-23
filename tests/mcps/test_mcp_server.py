"""Pruebas del servidor MCP de Brasaland (mcps/brasaland_mcp), contra un servidor REAL levantado por HTTP.

Cubren los criterios del ticket: discovery, OAuth (sin token no se lista ni se ejecuta nada), tools de tickets contra el
ciclo de vida, inventario de solo lectura con rechazo explícito, errores distintos entre sí y un log por invocación.

    python -m pytest tests/mcps
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp_support import FakeBackendApi, running_mcp_server

from mcps.brasaland_mcp import errors
from mcps.brasaland_mcp.domain import SCOPE_INVENTORY_READ, SCOPE_TICKETS_READ, SCOPE_TICKETS_WRITE
from mcps.brasaland_mcp.tools import TOOL_SCOPES

BACKEND = FakeBackendApi()


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    with running_mcp_server(tmp_path_factory.mktemp("mcp"), BACKEND) as running:
        yield running


@pytest.fixture(autouse=True)
def _reset_backend():
    fresh = FakeBackendApi()
    BACKEND.tickets, BACKEND.requests, BACKEND.mode = fresh.tickets, [], "ok"


def call(server, tool, arguments=None, *, scopes=(SCOPE_TICKETS_READ, SCOPE_TICKETS_WRITE, SCOPE_INVENTORY_READ)):
    """Invoca una tool con un token válido con esos scopes. Devuelve (is_error, texto, datos)."""
    url, issuer, _ = server

    async def run():
        headers = {"Authorization": f"Bearer {issuer.token(scopes=scopes)}"}
        async with Client(StreamableHttpTransport(url, headers=headers)) as client:
            result = await client.call_tool(tool, arguments or {}, raise_on_error=False)
            text = " ".join(getattr(block, "text", "") for block in result.content)
            return result.is_error, text, result.structured_content

    return asyncio.run(run())


def list_tools(server, token=None):
    url, issuer, _ = server

    async def run():
        headers = {"Authorization": f"Bearer {token or issuer.token()}"}
        async with Client(StreamableHttpTransport(url, headers=headers)) as client:
            return await client.list_tools()

    return asyncio.run(run())


def audit_lines(server) -> list[dict]:
    path: Path = server[2]
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


# --------------------------------------------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------------------------------------------
def test_the_server_exposes_its_tools_through_standard_mcp_discovery(server):
    tools = {tool.name: tool for tool in list_tools(server)}
    assert set(tools) == set(TOOL_SCOPES)
    assert {"incidents_create_ticket", "incidents_update_ticket_status", "incidents_get_ticket"} <= set(tools)


def test_every_tool_is_self_describing_without_reading_the_source(server):
    for tool in list_tools(server):
        assert len(tool.description) > 80, tool.name  # qué hace, errores y scope requerido
        assert f"Requiere el scope {TOOL_SCOPES[tool.name]}" in tool.description
        assert tool.meta["required_scope"] == TOOL_SCOPES[tool.name]
        schema = tool.inputSchema
        assert schema["additionalProperties"] is False
        for name, prop in schema.get("properties", {}).items():
            assert prop.get("description"), f"{tool.name}.{name} sin descripción"
        assert tool.outputSchema, f"{tool.name} sin esquema de salida"
        assert tool.annotations is not None


def test_read_only_tools_are_annotated_and_the_inventory_has_no_write_tool(server):
    tools = {tool.name: tool for tool in list_tools(server)}
    for name in ("incidents_get_ticket", "incidents_list_tickets", "inventory_get_stock"):
        assert tools[name].annotations.readOnlyHint is True
    assert tools["incidents_update_ticket_status"].annotations.readOnlyHint is False
    assert [name for name in tools if name.startswith("inventory_")] == ["inventory_get_stock"]


def test_the_schemas_use_the_domain_values_of_the_real_apis(server):
    create = next(t for t in list_tools(server) if t.name == "incidents_create_ticket").inputSchema["properties"]
    assert create["category"]["enum"] == ["Queja", "Solicitud", "Fallo operativo"]
    assert create["origin"]["enum"] == ["customer", "branch", "internal"]
    assert "Brasaland Laureles" in create["branch"]["enum"] and "central" in create["branch"]["enum"]
    status = next(t for t in list_tools(server) if t.name == "incidents_update_ticket_status").inputSchema
    assert status["properties"]["status"]["enum"] == ["open", "in_progress", "resolved", "discarded"]


def test_protected_resource_metadata_points_to_the_authorization_server(server):
    url, issuer, _ = server
    response = httpx.get(url.replace("/mcp", "/.well-known/oauth-protected-resource/mcp"))
    body = response.json()
    assert response.status_code == 200 and body["resource"] == url
    assert body["authorization_servers"] == [issuer.issuer]
    assert set(body["scopes_supported"]) == {SCOPE_TICKETS_READ, SCOPE_TICKETS_WRITE, SCOPE_INVENTORY_READ}


# --------------------------------------------------------------------------------------------------------------
# Autenticación (OAuth): sin token válido no se puede listar ni ejecutar
# --------------------------------------------------------------------------------------------------------------
def post_mcp(server, token=None):
    url, _, _ = server
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    headers["Accept"] = "application/json, text/event-stream"
    return httpx.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=headers)


def test_a_client_without_a_token_cannot_list_or_call_tools(server):
    response = post_mcp(server)
    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert challenge.startswith("Bearer") and 'error="missing_auth_header"' in challenge
    assert "/.well-known/oauth-protected-resource/mcp" in challenge  # dónde descubrir el servidor de autorización
    call_response = httpx.post(server[0], headers={"Accept": "application/json, text/event-stream"}, json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "incidents_list_tickets", "arguments": {}}})
    assert call_response.status_code == 401 and BACKEND.requests == []  # ni siquiera se tocó el backend


def test_invalid_tokens_are_rejected_each_with_its_own_reason(server):
    _, issuer, _ = server
    cases = {
        "basura": "esto-no-es-un-jwt",
        "expirado": issuer.token(expires_in=-3600),
        "audience equivocada": issuer.token(audience="https://otro-recurso.example.com"),
        "issuer equivocado": issuer.token(issuer="https://otro-emisor.example.com/"),
        "firmado con otra clave": issuer.token(key=issuer.other_key()),
    }
    reasons = {}
    for label, token in cases.items():
        response = post_mcp(server, token)
        assert response.status_code == 401, label
        reasons[label] = response.json()["error"]
    assert reasons["audience equivocada"] == "invalid_audience" and reasons["issuer equivocado"] == "invalid_issuer"
    assert reasons["basura"] == "invalid_token" and reasons["firmado con otra clave"] == "invalid_token"
    assert BACKEND.requests == []


def test_a_malformed_authorization_header_is_a_401_not_a_crash(server):
    response = httpx.post(server[0], headers={"Authorization": "Basic abc", "Accept": "application/json, text/event-stream"},
                          json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401 and response.json()["error"] == "invalid_auth_header_format"


def test_the_health_endpoint_is_public_and_exposes_no_company_data(server):
    response = httpx.get(server[0].replace("/mcp", "/healthz"))
    assert response.status_code == 200 and response.json() == {"status": "ok"}


# --------------------------------------------------------------------------------------------------------------
# Autorización (scopes / mínimo privilegio)
# --------------------------------------------------------------------------------------------------------------
def test_a_valid_token_without_the_tool_scope_gets_forbidden_scope_and_the_backend_is_untouched(server):
    is_error, text, _ = call(server, "incidents_create_ticket", {
        "title": "x", "description": "y", "category": "Queja", "origin": "branch", "branch": "central"},
        scopes=(SCOPE_TICKETS_READ,))
    assert is_error and text.startswith(f"[{errors.FORBIDDEN_SCOPE}]") and SCOPE_TICKETS_WRITE in text
    assert BACKEND.requests == []


def test_each_scope_opens_only_its_own_tools(server):
    read_only = (SCOPE_TICKETS_READ,)
    assert call(server, "incidents_get_ticket", {"ticket_id": 94}, scopes=read_only)[0] is False
    assert errors.FORBIDDEN_SCOPE in call(server, "inventory_get_stock", {}, scopes=read_only)[1]
    inventory_only = (SCOPE_INVENTORY_READ,)
    assert call(server, "inventory_get_stock", {}, scopes=inventory_only)[0] is False
    assert errors.FORBIDDEN_SCOPE in call(server, "incidents_get_ticket", {"ticket_id": 94}, scopes=inventory_only)[1]
    assert errors.FORBIDDEN_SCOPE in call(server, "incidents_update_ticket_status",
                                          {"ticket_id": 94, "status": "in_progress"}, scopes=read_only)[1]


def test_there_is_no_scope_that_allows_writing_inventory(server):
    assert not any(scope.startswith("inventory:") and scope != SCOPE_INVENTORY_READ for scope in TOOL_SCOPES.values())
    is_error, text, _ = call(server, "inventory_adjust_stock", {"product_id": 1, "quantity": 5},
                             scopes=("inventory:write", SCOPE_INVENTORY_READ, SCOPE_TICKETS_WRITE))
    assert is_error and errors.READ_ONLY_VIOLATION in text  # ni con un scope inventado


# --------------------------------------------------------------------------------------------------------------
# Tickets (contra el ciclo de vida del Incidents Manager)
# --------------------------------------------------------------------------------------------------------------
def test_get_and_list_tickets_return_the_fields_of_the_incident_api(server):
    _, _, ticket = call(server, "incidents_get_ticket", {"ticket_id": 94})
    assert set(ticket) == {"id", "title", "description", "category", "origin", "branch", "status", "created_at", "updated_at"}
    assert (ticket["id"], ticket["status"], ticket["branch"]) == (94, "open", "Brasaland Laureles")
    _, _, listing = call(server, "incidents_list_tickets", {"status": "resolved", "limit": 5})
    assert listing["total"] == 1 and listing["tickets"][0]["id"] == 90
    assert ("GET", "/api/incidents/94") in BACKEND.requests and ("GET", "/api/incidents") in BACKEND.requests


def test_create_ticket_posts_to_the_incidents_endpoint_with_the_domain_fields(server):
    is_error, _, created = call(server, "incidents_create_ticket", {
        "title": "Horno apagado", "description": "No enciende.", "category": "Fallo operativo",
        "origin": "branch", "branch": "Brasaland Laureles"})
    assert not is_error and created["status"] == "open" and created["id"] > 0
    assert ("POST", "/api/incidents") in BACKEND.requests


def test_status_changes_go_through_the_lifecycle_endpoint_never_a_generic_patch(server):
    is_error, _, updated = call(server, "incidents_update_ticket_status", {"ticket_id": 94, "status": "in_progress"})
    assert not is_error and updated["status"] == "in_progress"
    assert ("PATCH", "/api/incidents/94/status") in BACKEND.requests
    assert not [r for r in BACKEND.requests if r[0] == "PATCH" and not r[1].endswith("/status")]
    assert not any(r[0] in ("PUT", "DELETE") for r in BACKEND.requests)


def test_an_invalid_lifecycle_transition_is_reported_with_its_own_code(server):
    is_error, text, _ = call(server, "incidents_update_ticket_status", {"ticket_id": 90, "status": "open"})
    assert is_error and text.startswith(f"[{errors.INVALID_TRANSITION}]") and "resolved" in text


def test_unknown_ticket_and_invalid_arguments_have_distinct_codes(server):
    assert call(server, "incidents_get_ticket", {"ticket_id": 99999})[1].startswith(f"[{errors.NOT_FOUND}]")
    bad_value = call(server, "incidents_create_ticket", {"title": "x", "description": "y", "category": "Inventada",
                                                         "origin": "branch", "branch": "central"})
    assert bad_value[0] and bad_value[1].startswith(f"[{errors.VALIDATION_ERROR}]")
    bad_branch = call(server, "incidents_create_ticket", {"title": "x", "description": "y", "category": "Queja",
                                                          "origin": "branch", "branch": "Sede Inventada"})
    assert bad_branch[1].startswith(f"[{errors.VALIDATION_ERROR}]")
    assert call(server, "incidents_get_ticket", {"ticket_id": "abc"})[1].startswith(f"[{errors.VALIDATION_ERROR}]")
    assert call(server, "incidents_get_ticket", {"ticket_id": 94, "extra": 1})[1].startswith(f"[{errors.VALIDATION_ERROR}]")


# --------------------------------------------------------------------------------------------------------------
# Inventario: solo lectura, rechazada explícitamente cualquier escritura
# --------------------------------------------------------------------------------------------------------------
def test_inventory_answers_read_queries_from_the_real_endpoint(server):
    is_error, _, stock = call(server, "inventory_get_stock", {"product_name": "carbon"})
    assert not is_error and stock["products"][0]["current_stock"] == 15.5 and stock["products"][0]["sku"] == "CAR-001"
    assert call(server, "inventory_get_stock", {})[2]["total"] == 2
    assert call(server, "inventory_get_stock", {"product_name": "langosta"})[1].startswith(f"[{errors.NOT_FOUND}]")
    assert ("GET", "/inventory/products") in BACKEND.requests


@pytest.mark.parametrize("tool", ["inventory_update_stock", "inventory_set_stock", "inventory_adjust_stock",
                                  "inventory_create_product", "inventory_delete_product", "update_inventory",
                                  "delete_product", "restock_ingredient", "inventory_write"])
def test_any_write_tool_on_the_inventory_is_refused_explicitly(server, tool):
    is_error, text, _ = call(server, tool, {"product_id": 1, "quantity": 10})
    assert is_error and text.startswith(f"[{errors.READ_ONLY_VIOLATION}]") and "SOLO LECTURA" in text
    assert BACKEND.requests == []


@pytest.mark.parametrize("arguments", [{"product_id": 1, "quantity": 10}, {"product_id": 1, "set_stock": 0},
                                       {"product_name": "pollo", "operation": "delete"}, {"product_id": 1, "delta": -3}])
def test_write_arguments_on_the_read_tool_are_rejected_not_ignored(server, arguments):
    is_error, text, _ = call(server, "inventory_get_stock", arguments)
    assert is_error and text.startswith(f"[{errors.READ_ONLY_VIOLATION}]")
    assert BACKEND.requests == []  # la petición ni siquiera llegó al backend


def test_the_inventory_never_sends_anything_but_get_to_the_backend(server):
    call(server, "inventory_get_stock", {"product_name": "pollo"})
    call(server, "inventory_adjust_stock", {"product_id": 1, "quantity": 1})
    call(server, "inventory_get_stock", {"product_id": 1, "quantity": 1})
    inventory_calls = [r for r in BACKEND.requests if r[1].startswith("/inventory")]
    assert inventory_calls and {method for method, _ in inventory_calls} == {"GET"}


# --------------------------------------------------------------------------------------------------------------
# Fallos del backend
# --------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mode, code", [("timeout", errors.BACKEND_TIMEOUT), ("down", errors.BACKEND_UNAVAILABLE)])
def test_backend_failures_are_reported_with_stable_codes_and_no_internals(server, mode, code):
    BACKEND.mode = mode
    is_error, text, _ = call(server, "incidents_get_ticket", {"ticket_id": 94})
    assert is_error and text.startswith(f"[{code}]")
    assert "backend.test" not in text and "Traceback" not in text and "httpx" not in text


def test_all_error_families_use_different_codes():
    assert len(set(errors.ERROR_CODES)) == len(errors.ERROR_CODES) >= 8
    messages = list(errors.ERROR_CODES.values())
    assert len(set(messages)) == len(messages)


# --------------------------------------------------------------------------------------------------------------
# Trazabilidad: un log por invocación, con tool, cliente y resultado
# --------------------------------------------------------------------------------------------------------------
def test_every_invocation_leaves_one_audit_record_with_tool_client_and_result(server):
    before = len(audit_lines(server))
    call(server, "incidents_get_ticket", {"ticket_id": 94})
    call(server, "incidents_get_ticket", {"ticket_id": 99999})
    call(server, "inventory_adjust_stock", {"product_id": 1, "quantity": 1})
    call(server, "incidents_create_ticket", {"title": "x", "description": "y", "category": "Queja",
                                             "origin": "branch", "branch": "central"}, scopes=(SCOPE_TICKETS_READ,))
    records = audit_lines(server)[before:]
    assert [(r["tool"], r["outcome"], r["error_code"]) for r in records] == [
        ("incidents_get_ticket", "ok", None),
        ("incidents_get_ticket", "error", errors.NOT_FOUND),
        ("inventory_adjust_stock", "error", errors.READ_ONLY_VIOLATION),
        ("incidents_create_ticket", "error", errors.FORBIDDEN_SCOPE),
    ]
    assert all(r["client_id"] == "cliente-de-prueba" and r["ts"] and r["duration_ms"] >= 0 for r in records)


def test_the_audit_log_never_contains_tokens_or_free_text(server):
    call(server, "incidents_create_ticket", {"title": "SECRETO-EN-EL-TITULO", "description": "SECRETO-EN-LA-DESCRIPCION",
                                             "category": "Queja", "origin": "branch", "branch": "central"})
    raw = server[2].read_text(encoding="utf-8")
    assert "SECRETO" not in raw and "eyJ" not in raw and "Bearer" not in raw  # ni textos libres ni JWT


# --------------------------------------------------------------------------------------------------------------
# Decisiones de diseño verificables en el código
# --------------------------------------------------------------------------------------------------------------
def test_the_server_uses_mcp_auth_and_not_the_fastmcp_auth_layer():
    source = "\n".join(p.read_text(encoding="utf-8") for p in Path("mcps/brasaland_mcp").glob("*.py"))
    assert "from mcpauth import MCPAuth" in source and "bearer_auth_middleware" in source and "resource_metadata_router" in source
    assert not re.search(r"fastmcp\.server\.auth|auth=|OAuthProxy|JWTVerifier|TokenVerifier", source)


def test_the_transport_is_streamable_http_in_stateless_mode():
    source = Path("mcps/brasaland_mcp/server.py").read_text(encoding="utf-8")
    assert "stateless_http=True" in source and "stdio" in source.lower()  # y la docstring explica por qué no stdio
