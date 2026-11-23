"""Pruebas de las tools del agente (tickets e inventario): contrato, solo lectura, auth, timeout y fallos.

El backend HTTP es `FakeBackend` (solo en pruebas). Contra el backend REAL se prueba en
`services/api/tests/test_agent_tools_integration.py`.

    python -m pytest tests/pipelines/test_agent_tools.py
"""
from __future__ import annotations

import httpx
import pytest
from agent_support import FakeBackend
from pydantic import ValidationError

from services.agent import tools
from services.agent.tools import (
    BackendClient,
    InventoryQuery,
    InventoryTool,
    TicketQuery,
    TicketTool,
    ToolOutcome,
)


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
    result = TicketTool(backend.client())(TicketQuery(ticket_id=482))
    assert result.outcome is ToolOutcome.OK and result.total == 1
    ticket = result.tickets[0]
    assert (ticket.id, ticket.status, ticket.category, ticket.origin, ticket.branch) == (
        482, "in_progress", "Fallo operativo", "branch", "Brasaland Laureles")
    assert ticket.created_at and ticket.updated_at


def test_ticket_list_filters_by_status_and_respects_limit(backend):
    result = TicketTool(backend.client())(TicketQuery(status="open", limit=1))
    assert [t.id for t in result.tickets] == [12] and result.total == 1
    assert ("GET", "/api/incidents") in backend.requests
    everything = TicketTool(backend.client())(TicketQuery(limit=2))
    assert len(everything.tickets) == 2 and everything.total == 3


def test_unknown_ticket_is_not_found_not_an_error(backend):
    result = TicketTool(backend.client())(TicketQuery(ticket_id=9999))
    assert result.outcome is ToolOutcome.NOT_FOUND and result.tickets == []


def test_inventory_by_name_ignores_case_and_accents(backend):
    result = InventoryTool(backend.client())(InventoryQuery(product_name="CARBON"))
    assert result.outcome is ToolOutcome.OK and [p.name for p in result.products] == ["Carbón vegetal"]
    assert result.products[0].current_stock == 15.5
    assert InventoryTool(backend.client())(InventoryQuery(product_name="langosta")).outcome is ToolOutcome.NOT_FOUND
    assert len(InventoryTool(backend.client())(InventoryQuery()).products) == 2


# --- solo lectura ---------------------------------------------------------------------------------------------
def test_tools_only_ever_send_get_requests_apart_from_the_login(backend):
    TicketTool(backend.client())(TicketQuery(ticket_id=482))
    TicketTool(backend.client())(TicketQuery(status="open"))
    InventoryTool(backend.client())(InventoryQuery(product_name="pollo"))
    assert {method for method, _ in backend.requests} == {"GET", "POST"}
    assert [path for method, path in backend.requests if method == "POST"] == ["/auth/login"] * 3


def test_the_client_has_no_way_to_write():
    public = {name for name in dir(BackendClient) if not name.startswith("_")}
    assert public == {"get"}
    assert not {"post", "put", "patch", "delete"} & public


# --- autenticación --------------------------------------------------------------------------------------------
def test_token_is_requested_once_and_reused(backend):
    client = backend.client()
    TicketTool(client)(TicketQuery(ticket_id=482))
    TicketTool(client)(TicketQuery(ticket_id=12))
    assert [path for method, path in backend.requests if method == "POST"] == ["/auth/login"]


def test_an_expired_token_is_renewed_once(backend):
    client = backend.client()
    client._token = "caducado"
    assert TicketTool(client)(TicketQuery(ticket_id=482)).outcome is ToolOutcome.OK


def test_credentials_come_from_the_environment_never_from_code(backend, monkeypatch):
    monkeypatch.setenv("AGENT_API_EMAIL", "env@brasaland.test")
    monkeypatch.setenv("AGENT_API_PASSWORD", "desde-el-entorno")
    client = BackendClient(base_url="http://backend.test", transport=httpx.MockTransport(backend.handler))
    assert TicketTool(client)(TicketQuery(ticket_id=482)).outcome is ToolOutcome.OK


def test_missing_credentials_are_reported_without_calling_the_service(backend, monkeypatch):
    monkeypatch.delenv("AGENT_API_EMAIL", raising=False)
    monkeypatch.delenv("AGENT_API_PASSWORD", raising=False)
    client = BackendClient(base_url="http://backend.test", transport=httpx.MockTransport(backend.handler))
    result = TicketTool(client)(TicketQuery(ticket_id=482))
    assert result.outcome is ToolOutcome.UNAUTHORIZED and backend.requests == []


def test_rejected_credentials_are_reported_as_unauthorized():
    result = TicketTool(FakeBackend(token_valid=False).client())(TicketQuery(ticket_id=482))
    assert result.outcome is ToolOutcome.UNAUTHORIZED


# --- timeout y fallos -----------------------------------------------------------------------------------------
def test_there_is_an_explicit_numeric_timeout():
    assert isinstance(tools.TOOL_TIMEOUT_SECONDS, float) and 0 < tools.TOOL_TIMEOUT_SECONDS <= 5
    client = FakeBackend().client()
    assert client.timeout == tools.TOOL_TIMEOUT_SECONDS
    assert client._http.timeout == httpx.Timeout(tools.TOOL_TIMEOUT_SECONDS)


@pytest.mark.parametrize("mode, outcome", [
    ("timeout", ToolOutcome.TIMEOUT), ("down", ToolOutcome.UNAVAILABLE), ("error", ToolOutcome.UNAVAILABLE)])
def test_a_failing_service_never_raises_and_says_why(mode, outcome):
    for call in (lambda c: TicketTool(c)(TicketQuery(ticket_id=482)), lambda c: InventoryTool(c)(InventoryQuery())):
        result = call(FakeBackend(mode=mode).client())
        assert result.outcome is outcome and result.error
        assert "backend.test" not in result.error and "Traceback" not in result.error  # sin URLs ni stack traces


def test_an_unexpected_response_shape_is_a_failure_not_a_crash():
    backend = FakeBackend(tickets=[{"id": "no-es-un-numero"}])
    assert TicketTool(backend.client())(TicketQuery()).outcome is ToolOutcome.UNAVAILABLE


# --- una responsabilidad por tool ----------------------------------------------------------------------------
def test_each_tool_has_a_single_responsibility(backend):
    TicketTool(backend.client())(TicketQuery(status="open"))
    assert {path for _, path in backend.requests if path != "/auth/login"} == {"/api/incidents"}
    backend.requests.clear()
    InventoryTool(backend.client())(InventoryQuery())
    assert {path for _, path in backend.requests if path != "/auth/login"} == {"/inventory/products"}
