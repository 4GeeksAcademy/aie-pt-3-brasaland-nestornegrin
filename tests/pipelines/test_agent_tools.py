"""Pruebas de las tools del agente (tickets e inventario) sobre MCP: contrato, solo lectura, OAuth, timeout y fallos.

Aquí el servidor MCP es `FakeBackend` (doble en memoria, solo en pruebas). El agente contra el servidor MCP REAL
(HTTP + OAuth) se prueba en `tests/mcps/test_agent_via_mcp.py`.

    python -m pytest tests/pipelines/test_agent_tools.py
"""
from __future__ import annotations

import ast
import inspect

import httpx
import pytest
from agent_support import FakeBackend
from pydantic import ValidationError

from services.agent import mcp_tools, nodes, tools
from services.agent.mcp_tools import (
    McpCallError,
    McpGateway,
    McpInventoryTool,
    McpTicketTool,
    TokenProvider,
)
from services.agent.tools import InventoryQuery, TicketQuery, ToolOutcome


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


def test_ticket_contract_is_typed():
    assert TicketQuery(ticket_id=482).ticket_id == 482
    for bad in ({"ticket_id": 0}, {"ticket_id": "abc"}, {"status": "inventado"}, {"limit": 0}, {"limit": 99}, {"otro": 1}):
        with pytest.raises(ValidationError):
            TicketQuery(**bad)
    with pytest.raises(ValidationError):
        InventoryQuery(product_id=-1)


def test_ticket_by_id_returns_the_fields_of_the_incident_api(backend):
    result = McpTicketTool(backend.client())(TicketQuery(ticket_id=482))
    assert result.outcome is ToolOutcome.OK and result.total == 1
    ticket = result.tickets[0]
    assert (ticket.id, ticket.status, ticket.category, ticket.origin, ticket.branch) == (
        482, "in_progress", "Fallo operativo", "branch", "Brasaland Laureles")
    assert ticket.created_at and ticket.updated_at


def test_ticket_list_filters_by_status_and_respects_limit(backend):
    result = McpTicketTool(backend.client())(TicketQuery(status="open", limit=1))
    assert [t.id for t in result.tickets] == [12] and result.total == 1
    assert ("MCP", "incidents_list_tickets") in backend.requests
    everything = McpTicketTool(backend.client())(TicketQuery(limit=2))
    assert len(everything.tickets) == 2 and everything.total == 3


def test_unknown_ticket_is_not_found_not_an_error(backend):
    result = McpTicketTool(backend.client())(TicketQuery(ticket_id=9999))
    assert result.outcome is ToolOutcome.NOT_FOUND and result.tickets == []


def test_inventory_by_name_ignores_case_and_accents(backend):
    result = McpInventoryTool(backend.client())(InventoryQuery(product_name="CARBON"))
    assert result.outcome is ToolOutcome.OK and [p.name for p in result.products] == ["Carbón vegetal"]
    assert result.products[0].current_stock == 15.5
    assert McpInventoryTool(backend.client())(InventoryQuery(product_name="langosta")).outcome is ToolOutcome.NOT_FOUND
    assert len(McpInventoryTool(backend.client())(InventoryQuery()).products) == 2


# --- un solo camino: MCP, y de solo lectura ------------------------------------------------------------------
def test_the_agent_only_invokes_read_tools_on_the_mcp_server(backend):
    McpTicketTool(backend.client())(TicketQuery(ticket_id=482))
    McpTicketTool(backend.client())(TicketQuery(status="open"))
    McpInventoryTool(backend.client())(InventoryQuery(product_name="pollo"))
    assert {tool for _, tool in backend.requests} == {"incidents_get_ticket", "incidents_list_tickets", "inventory_get_stock"}


def test_the_direct_tools_are_gone_so_there_is_no_second_path():
    for name in ("TicketTool", "InventoryTool", "BackendClient", "classify_failure"):
        assert not hasattr(tools, name), f"{name} debía eliminarse de services/agent/tools.py"
    source = inspect.getsource(nodes) + inspect.getsource(mcp_tools)
    imported = {alias.name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom) for alias in node.names}
    assert not imported & {"TicketTool", "InventoryTool", "BackendClient"}
    deps = nodes.default_dependencies.__code__.co_names
    assert "McpTicketTool" in deps and "McpInventoryTool" in deps and "TicketTool" not in deps


def test_the_agent_never_talks_http_to_the_backend_services():
    for module in (nodes, mcp_tools):
        source = inspect.getsource(module)
        assert "/api/incidents" not in source and "/inventory/products" not in source and "AGENT_API_" not in source


# --- autenticación OAuth del agente ---------------------------------------------------------------------------
def _token_endpoint(requests: list, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, json={"access_token": f"jwt-{len(requests)}", "expires_in": 3600})
    return httpx.Client(transport=httpx.MockTransport(handler))


def _provider(http, **kwargs) -> TokenProvider:
    values = dict(token_url="https://idp.test/oauth/token", client_id="agente", client_secret="s3cret",
                  audience="https://mcp.test/mcp", http=http)
    return TokenProvider(**(values | kwargs))


def test_the_token_is_requested_with_client_credentials_and_read_scopes_only():
    requests: list = []
    token = _provider(_token_endpoint(requests)).get()
    body = dict(pair.split("=") for pair in requests[0].content.decode().split("&"))
    assert token == "jwt-1" and body["grant_type"] == "client_credentials"
    assert body["scope"] == "tickets%3Aread+inventory%3Aread"  # nunca tickets:write
    assert "write" not in body["scope"]


def test_the_token_is_cached_until_it_expires():
    requests: list = []
    provider = _provider(_token_endpoint(requests))
    assert provider.get() == provider.get() and len(requests) == 1
    provider.invalidate()
    assert provider.get() == "jwt-2"


def test_credentials_come_from_the_environment_never_from_code(monkeypatch):
    requests: list = []
    monkeypatch.setenv("AGENT_MCP_TOKEN_URL", "https://idp.test/oauth/token")
    monkeypatch.setenv("AGENT_MCP_CLIENT_ID", "desde-env")
    monkeypatch.setenv("AGENT_MCP_CLIENT_SECRET", "secreto-env")
    monkeypatch.setenv("MCP_SERVER_URL", "https://mcp.test/mcp")
    provider = TokenProvider(http=_token_endpoint(requests))
    assert provider.get() == "jwt-1" and provider.audience == "https://mcp.test/mcp"


def test_missing_credentials_are_reported_without_calling_anything(monkeypatch):
    for var in ("AGENT_MCP_TOKEN_URL", "AGENT_MCP_CLIENT_ID", "AGENT_MCP_CLIENT_SECRET", "MCP_SERVER_URL"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(McpCallError) as error:
        TokenProvider().get()
    assert error.value.code == "MCP_NOT_CONFIGURED"
    result = McpTicketTool(McpGateway())(TicketQuery(ticket_id=1))  # sin MCP_SERVER_URL
    assert result.outcome is ToolOutcome.UNAUTHORIZED


def test_rejected_credentials_are_reported_as_unauthorized():
    with pytest.raises(McpCallError) as error:
        _provider(_token_endpoint([], status=401)).get()
    assert error.value.code == "MCP_UNAUTHORIZED"
    assert McpTicketTool(FakeBackend(token_valid=False).client())(TicketQuery(ticket_id=482)).outcome is ToolOutcome.UNAUTHORIZED


# --- timeout y fallos -----------------------------------------------------------------------------------------
def test_there_is_an_explicit_numeric_timeout():
    assert isinstance(mcp_tools.CALL_TIMEOUT_SECONDS, float) and 0 < mcp_tools.CALL_TIMEOUT_SECONDS <= 10
    assert McpGateway(server_url="https://mcp.test/mcp", token_provider=object()).timeout == mcp_tools.CALL_TIMEOUT_SECONDS


@pytest.mark.parametrize("mode, outcome", [
    ("timeout", ToolOutcome.TIMEOUT), ("down", ToolOutcome.UNAVAILABLE), ("error", ToolOutcome.UNAVAILABLE)])
def test_a_failing_service_never_raises_and_says_why(mode, outcome):
    for call in (lambda c: McpTicketTool(c)(TicketQuery(ticket_id=482)), lambda c: McpInventoryTool(c)(InventoryQuery())):
        result = call(FakeBackend(mode=mode).client())
        assert result.outcome is outcome and result.error
        assert "backend.test" not in result.error and "Traceback" not in result.error  # sin URLs ni stack traces


@pytest.mark.parametrize("code, outcome", [
    ("NOT_FOUND", ToolOutcome.NOT_FOUND), ("FORBIDDEN_SCOPE", ToolOutcome.UNAUTHORIZED),
    ("VALIDATION_ERROR", ToolOutcome.INVALID), ("READ_ONLY_VIOLATION", ToolOutcome.INVALID),
    ("BACKEND_TIMEOUT", ToolOutcome.TIMEOUT), ("BACKEND_UNAVAILABLE", ToolOutcome.UNAVAILABLE),
    ("INTERNAL_ERROR", ToolOutcome.UNAVAILABLE)])
def test_every_server_error_code_maps_to_a_graph_outcome(code, outcome):
    assert mcp_tools.failure(code, "tickets")[0] is outcome


def test_server_error_text_is_parsed_into_its_code():
    with pytest.raises(McpCallError) as error:
        McpGateway._parse([{"type": "text", "text": "[NOT_FOUND] Incidencia no encontrada"}])
    assert error.value.code == "NOT_FOUND"
    assert McpGateway._parse([{"type": "text", "text": '{"id": 1}'}]) == {"id": 1}


def test_an_unexpected_response_shape_is_a_failure_not_a_crash():
    backend = FakeBackend(tickets=[{"id": "no-es-un-numero"}])
    assert McpTicketTool(backend.client())(TicketQuery()).outcome is ToolOutcome.UNAVAILABLE


# --- una responsabilidad por tool ----------------------------------------------------------------------------
def test_each_tool_has_a_single_responsibility(backend):
    McpTicketTool(backend.client())(TicketQuery(status="open"))
    assert {tool for _, tool in backend.requests} == {"incidents_list_tickets"}
    backend.requests.clear()
    McpInventoryTool(backend.client())(InventoryQuery())
    assert {tool for _, tool in backend.requests} == {"inventory_get_stock"}
