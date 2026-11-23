"""Pruebas del enrutador (`plan_route`) y de los nodos/aristas de la Parte 2 (tools)."""
from __future__ import annotations

import pytest
from agent_support import FakeBackend, SpyDependencies
from langgraph.checkpoint.memory import InMemorySaver

from services.agent import nodes
from services.agent.routing import plan_route
from services.agent.service import AgentService
from services.agent.tracing import TraceStore


@pytest.mark.parametrize("question, sources", [
    ("¿En qué estado está el ticket 482?", ["tickets"]),
    ("¿Cómo va la incidencia #12?", ["tickets"]),
    ("¿Cuántas incidencias abiertas hay?", ["tickets"]),
    ("¿Tenemos stock de pollo?", ["inventory"]),
    ("¿Cuánto queda de carbón?", ["inventory"]),
    ("¿Cuántos puntos hay que acumular para el nivel Oro?", ["rag"]),
    ("¿Cuándo hay que escribir una nota por desperdicio de proteína?", ["rag"]),
    ("¿Hay versión sin gluten de las Costillas BBQ?", ["rag"]),
    ("¿Cómo se registra una incidencia?", ["rag"]),  # menciona incidencias, pero es un procedimiento, no un estado
    ("¿Cuál es la capital de Francia?", ["rag"]),  # sin señal de datos en vivo -> RAG (dirá "no tengo información")
    ("Según el protocolo de merma, ¿en qué estado está el ticket 12?", ["tickets", "rag"]),
])
def test_plan_route_picks_the_sources_from_the_question(question, sources):
    plan = plan_route(question)
    assert list(plan.sources) == sources and plan.reason


def test_plan_route_extracts_the_query_for_each_tool():
    assert plan_route("¿En qué estado está el ticket 482?").ticket_query == {"ticket_id": 482}
    assert plan_route("¿Cuántas incidencias abiertas hay?").ticket_query == {"ticket_id": None, "status": "open"}
    assert plan_route("incidencias en progreso").ticket_query["status"] == "in_progress"
    assert plan_route("¿Tenemos stock de pollo entero?").inventory_query == {"product_name": "pollo entero"}



def test_tool_nodes_degrade_to_unavailable_when_the_tool_is_not_configured(tmp_path):
    spy = SpyDependencies()
    service = AgentService(spy.deps, checkpointer=InMemorySaver(), trace_store=TraceStore(tmp_path))
    run = service.run("¿En qué estado está el ticket 482?")
    assert run.status == "tool_fallback" and "No pude confirmar" in run.answer and spy.generate_calls == []


def test_the_trace_names_the_route_and_the_sources_in_order(tmp_path):
    backend = FakeBackend()
    service = AgentService(backend.dependencies(), checkpointer=InMemorySaver(), trace_store=TraceStore(tmp_path))
    run = service.run("Según el protocolo de merma, ¿en qué estado está el ticket 12?")
    trace = service.trace_store.load(run.run_id)
    assert trace["route"]["sources"] == ["tickets", "rag"] and "ticket 12" in trace["route"]["reason"]
    assert [(s["source"], s["order"]) for s in trace["sources_used"]] == [("tool:tickets", 3), ("rag", 4)]
    assert trace["sources_used"][0]["outcome"] == "ok" and trace["sources_used"][1]["chunks"] >= 1
    assert run.sources == ["tool:tickets", "rag"]


def test_tool_chunks_only_include_successful_results():
    ok = {"tool": "tickets", "outcome": "ok", "query": {}, "result": {"total": 1, "tickets": [{
        "id": 1, "title": "t", "description": "d", "category": "c", "origin": "o", "branch": "b",
        "status": "open", "created_at": "x", "updated_at": "y"}]}}
    failed = {"tool": "inventory", "outcome": "timeout", "query": {}, "result": {}}
    chunks = nodes.tool_chunks([ok, failed])
    assert len(chunks) == 1 and "Estado: abierto" in chunks[0]["text"]
    assert chunks[0]["source_document"] == nodes.LIVE_SOURCE["tickets"]


def test_a_route_without_tools_never_touches_them(tmp_path):
    backend = FakeBackend()
    service = AgentService(backend.dependencies(), checkpointer=InMemorySaver(), trace_store=TraceStore(tmp_path))
    service.run("¿Cuántos puntos hay que acumular para el nivel Oro?")
    assert backend.requests == []
