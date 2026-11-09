"""El agente LangGraph consumiendo el servidor MCP REAL (HTTP + OAuth), con `langchain-mcp-adapters`.

Se levanta el servidor MCP completo (con su validación JWT) y el agente usa `McpGateway` de verdad: discovery, Bearer y
tool. Solo es de prueba el emisor OAuth (`LocalIssuer`) y el backend de datos (`FakeBackendApi`). El RAG se sustituye por
un doble determinista.

    python -m pytest tests/mcps/test_agent_via_mcp.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from mcp_support import FakeBackendApi, running_mcp_server

sys.path.insert(0, str(Path(__file__).parent.parent / "pipelines"))
from agent_support import SpyDependencies  # noqa: E402

from mcps.brasaland_mcp.domain import SCOPE_INVENTORY_READ, SCOPE_TICKETS_READ  # noqa: E402
from services.agent import nodes  # noqa: E402
from services.agent.mcp_tools import McpGateway, McpInventoryTool, McpTicketTool  # noqa: E402
from services.agent.nodes import AgentDependencies  # noqa: E402
from services.agent.service import AgentService  # noqa: E402
from services.agent.state import STATUS_ANSWERED, STATUS_TOOL_FALLBACK  # noqa: E402
from services.agent.tracing import TraceStore  # noqa: E402

BACKEND = FakeBackendApi()


class StaticToken:
    """Sustituye al proveedor OAuth: entrega un JWT firmado por el emisor de prueba con los scopes indicados."""

    def __init__(self, issuer, scopes):
        self.issuer, self.scopes = issuer, scopes

    def get(self) -> str:
        return self.issuer.token(scopes=self.scopes, client_id="agente-brasaland")

    def invalidate(self) -> None:
        pass


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    with running_mcp_server(tmp_path_factory.mktemp("agent-mcp"), BACKEND) as running:
        yield running


@pytest.fixture(autouse=True)
def _reset():
    fresh = FakeBackendApi()
    BACKEND.tickets, BACKEND.requests, BACKEND.mode = fresh.tickets, [], "ok"


def make_agent(server, tmp_path, scopes=(SCOPE_TICKETS_READ, SCOPE_INVENTORY_READ)) -> tuple[AgentService, SpyDependencies]:
    url, issuer, _ = server
    gateway = McpGateway(server_url=url, token_provider=StaticToken(issuer, scopes), timeout=10)
    rag = SpyDependencies()
    deps = AgentDependencies(rag.retrieve, rag.generate, McpTicketTool(gateway), McpInventoryTool(gateway))
    return AgentService(deps, checkpointer=InMemorySaver(), trace_store=TraceStore(tmp_path)), rag


def audit(server) -> list[dict]:
    import json
    return [json.loads(line) for line in server[2].read_text(encoding="utf-8").splitlines() if line.strip()]


def test_a_ticket_question_goes_through_the_mcp_server_and_not_the_rag(server, tmp_path):
    agent, rag = make_agent(server, tmp_path)
    run = agent.run("¿Cuál es el estado del ticket 94?")
    trace = agent.trace_store.load(run.run_id)
    assert trace["status"] == STATUS_ANSWERED and [s["source"] for s in trace["sources_used"]] == ["tool:tickets"]
    assert nodes.NODE_RETRIEVE not in trace["node_order"] and rag.retrieve_calls == []
    assert "Nevera averiada" in str(trace["final_state"]) or "open" in run.answer.lower()
    records = [r for r in audit(server) if r["client_id"] == "agente-brasaland"]
    assert [(r["tool"], r["outcome"]) for r in records][-1] == ("incidents_get_ticket", "ok")  # lo vio el servidor MCP
    assert ("GET", "/api/incidents/94") in BACKEND.requests


def test_a_stock_question_uses_the_read_only_inventory_tool(server, tmp_path):
    agent, _ = make_agent(server, tmp_path)
    run = agent.run("¿Cuál es el stock de pollo?")
    trace = agent.trace_store.load(run.run_id)
    assert trace["status"] == STATUS_ANSWERED and [s["source"] for s in trace["sources_used"]] == ["tool:inventory"]
    assert {m for m, p in BACKEND.requests if p.startswith("/inventory")} == {"GET"}
    assert audit(server)[-1]["tool"] == "inventory_get_stock"


def test_knowledge_questions_still_use_the_rag_and_never_touch_mcp(server, tmp_path):
    agent, rag = make_agent(server, tmp_path)
    before = len(audit(server))
    run = agent.run("¿Cuántos puntos hay que acumular para el nivel Oro?")
    assert run.status == STATUS_ANSWERED and rag.retrieve_calls and len(audit(server)) == before


def test_a_token_without_the_needed_scope_degrades_to_an_honest_fallback(server, tmp_path):
    agent, _ = make_agent(server, tmp_path, scopes=(SCOPE_INVENTORY_READ,))  # sin tickets:read
    run = agent.run("¿Cuál es el estado del ticket 94?")
    trace = agent.trace_store.load(run.run_id)
    assert trace["status"] == STATUS_TOOL_FALLBACK and "Nevera averiada" not in run.answer
    assert "unauthorized" in str(trace["final_state"]["tool_results"])  # el resultado de la tool lo dice
    assert audit(server)[-1]["error_code"] == "FORBIDDEN_SCOPE"


def test_if_the_backend_is_down_the_agent_says_so_instead_of_inventing(server, tmp_path):
    BACKEND.mode = "down"
    agent, _ = make_agent(server, tmp_path)
    run = agent.run("¿Cuál es el estado del ticket 94?")
    assert agent.trace_store.load(run.run_id)["status"] == STATUS_TOOL_FALLBACK and "Nevera averiada" not in run.answer


def test_an_unreachable_mcp_server_is_a_fallback_not_a_crash(tmp_path):
    gateway = McpGateway(server_url="http://127.0.0.1:9/mcp", timeout=3,
                         token_provider=type("T", (), {"get": lambda self: "x", "invalidate": lambda self: None})())
    rag = SpyDependencies()
    agent = AgentService(AgentDependencies(rag.retrieve, rag.generate, McpTicketTool(gateway), McpInventoryTool(gateway)),
                         checkpointer=InMemorySaver(), trace_store=TraceStore(tmp_path))
    run = agent.run("¿Cuál es el estado del ticket 94?")
    assert agent.trace_store.load(run.run_id)["status"] == STATUS_TOOL_FALLBACK
