"""Evals de la Parte 2: enrutamiento RAG / tool y ruta de fallback. Cada comprobación se hace sobre el TRACE.

Corren sin red ni claves: el RAG es la base real indexada en un Qdrant en memoria (embedding falso) con un generador
extractivo, y el backend HTTP es `FakeBackend` (solo en pruebas; el contrato contra el backend real se prueba en
`services/api/tests/test_agent_tools_integration.py`).

    python -m pytest tests/pipelines/test_agent_tools_evals.py          # un solo comando
    AGENT_TOOLS_EVAL_RESULTS=docs/agent/tools-eval-results.json python -m pytest tests/pipelines/test_agent_tools_evals.py -v
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from agent_support import FakeBackend, extractive_generate, fake_embed
from langgraph.checkpoint.memory import InMemorySaver
from qdrant_client import QdrantClient

from data.pipelines import rag as pipeline
from data.process import rag as process
from services.agent import nodes
from services.agent.nodes import AgentDependencies
from services.agent.service import AgentService
from services.agent.state import STATUS_ANSWERED, STATUS_TOOL_FALLBACK
from services.agent.tools import InventoryTool, TicketTool
from services.agent.tracing import TraceStore

FAKE_MIN_SCORE = 0.30
TICKET_QUESTION = "¿En qué estado está el ticket 482?"
RAG_QUESTION = "¿Cuántos puntos hay que acumular para el nivel Oro y qué descuento permanente da?"
BOTH_QUESTION = "Según el protocolo de merma, ¿en qué estado está el ticket 12?"
STOCK_QUESTION = "¿Tenemos stock de pollo?"

_RESULTS: list[dict] = []


class Counting:
    """Cuenta cuántas veces se llama a recuperar y a generar (para comprobar qué fuentes se usaron)."""

    def __init__(self, client: QdrantClient):
        self.client = client
        self.retrievals = 0
        self.generations = 0
        self.generated_context: list[dict] = []

    def retrieve(self, question: str) -> list[dict]:
        self.retrievals += 1
        return pipeline.retrieve(question, min_score=FAKE_MIN_SCORE, client=self.client, embed_fn=fake_embed)

    def generate(self, question: str, context: list[dict]) -> str:
        self.generations += 1
        self.generated_context = context
        return extractive_generate(question, context)


@pytest.fixture(scope="module")
def knowledge_client() -> QdrantClient:
    client = QdrantClient(":memory:")
    process.setup(client=client, embed_fn=fake_embed)
    return client


@pytest.fixture
def counting(knowledge_client) -> Counting:
    return Counting(knowledge_client)


def make_agent(backend: FakeBackend, counting: Counting, tmp_path) -> AgentService:
    client = backend.client()
    deps = AgentDependencies(counting.retrieve, counting.generate, TicketTool(client), InventoryTool(client))
    return AgentService(deps, checkpointer=InMemorySaver(), trace_store=TraceStore(tmp_path / "traces"))


def _record(name: str, passed: bool, detail: str) -> None:
    _RESULTS.append({"eval": name, "passed": passed, "detail": detail})


@pytest.fixture(scope="module", autouse=True)
def _save_results():
    yield
    target = os.environ.get("AGENT_TOOLS_EVAL_RESULTS")
    if target:
        Path(target).write_text(json.dumps({"results": _RESULTS}, ensure_ascii=False, indent=2), encoding="utf-8")


def _api_calls(backend: FakeBackend) -> list[tuple[str, str]]:
    return [call for call in backend.requests if call[1] != "/auth/login"]


# --------------------------------------------------------------------------------------------------------------
# Eval 1 — una pregunta de datos en vivo se resuelve con la tool, NO con el RAG
# --------------------------------------------------------------------------------------------------------------
def test_eval_ticket_question_is_resolved_by_the_tool_not_the_rag(counting, tmp_path):
    backend = FakeBackend()
    agent = make_agent(backend, counting, tmp_path)
    run = agent.run(TICKET_QUESTION)
    trace = agent.trace_store.load(run.run_id)
    ok = (
        trace["status"] == STATUS_ANSWERED
        and [item["source"] for item in trace["sources_used"]] == ["tool:tickets"]
        and trace["node_order"] == [nodes.NODE_RECEIVE, nodes.NODE_ROUTE, nodes.NODE_TICKETS, nodes.NODE_GENERATE]
        and trace["route"]["sources"] == ["tickets"]
        and counting.retrievals == 0  # el RAG no se consultó
        and "Estado: en progreso" in trace["final_state"]["answer"]  # el dato sale del ticket 482 del backend
        and _api_calls(backend) == [("GET", "/api/incidents/482")]
    )
    _record("routing:ticket_question_uses_tool", ok, f"fuentes={trace['sources_used']}")
    assert ok, trace["node_order"]


# --------------------------------------------------------------------------------------------------------------
# Eval 2 — una pregunta de conocimiento se resuelve con el RAG, NO con una tool
# --------------------------------------------------------------------------------------------------------------
def test_eval_knowledge_question_is_resolved_by_the_rag_not_a_tool(counting, tmp_path):
    backend = FakeBackend()
    agent = make_agent(backend, counting, tmp_path)
    run = agent.run(RAG_QUESTION)
    trace = agent.trace_store.load(run.run_id)
    ok = (
        trace["status"] == STATUS_ANSWERED
        and [item["source"] for item in trace["sources_used"]] == ["rag"]
        and nodes.NODE_TICKETS not in trace["node_order"] and nodes.NODE_INVENTORY not in trace["node_order"]
        and backend.requests == []  # no se llamó al backend (ni siquiera al login)
        and "50+ puntos" in trace["final_state"]["answer"]
    )
    _record("routing:knowledge_question_uses_rag", ok, f"fuentes={trace['sources_used']}")
    assert ok, trace["node_order"]


# --------------------------------------------------------------------------------------------------------------
# Eval 3 — una pregunta mixta usa ambos, en orden (primero el dato en vivo, luego el RAG)
# --------------------------------------------------------------------------------------------------------------
def test_eval_mixed_question_uses_both_sources_in_order(counting, tmp_path):
    backend = FakeBackend()
    agent = make_agent(backend, counting, tmp_path)
    run = agent.run(BOTH_QUESTION)
    trace = agent.trace_store.load(run.run_id)
    documents = {chunk["source_document"] for chunk in counting.generated_context}
    ok = (
        trace["status"] == STATUS_ANSWERED
        and [item["source"] for item in trace["sources_used"]] == ["tool:tickets", "rag"]
        and trace["node_order"] == [nodes.NODE_RECEIVE, nodes.NODE_ROUTE, nodes.NODE_TICKETS, nodes.NODE_RETRIEVE,
                                    nodes.NODE_GENERATE]
        and counting.generations == 1  # una sola generación con las dos evidencias
        and "waste-protocol" in documents and nodes.LIVE_SOURCE["tickets"] in documents
    )
    _record("routing:mixed_question_uses_both_in_order", ok, f"fuentes={trace['sources_used']}")
    assert ok, documents


# --------------------------------------------------------------------------------------------------------------
# Eval 4 — fallback: el servicio no responde a tiempo -> respuesta honesta, sin inventar un estado, sin generar
# --------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mode, outcome", [("timeout", "timeout"), ("down", "unavailable"), ("error", "unavailable")])
def test_eval_tool_failure_falls_back_honestly_without_inventing_a_status(counting, tmp_path, mode, outcome):
    agent = make_agent(FakeBackend(mode=mode), counting, tmp_path)
    run = agent.run(TICKET_QUESTION)
    trace = agent.trace_store.load(run.run_id)
    answer = trace["final_state"]["answer"]
    invented = any(word in answer.lower() for word in ("en progreso", "abierto", "resuelto", "descartado"))
    ok = (
        trace["status"] == STATUS_TOOL_FALLBACK
        and trace["node_order"][-1] == nodes.NODE_TOOL_FALLBACK
        and trace["sources_used"][0]["outcome"] == outcome
        and "No pude confirmar el estado del ticket 482" in answer
        and not invented
        and counting.generations == 0  # no se genera sin evidencia
    )
    _record(f"fallback:service_{mode}", ok, f"outcome={outcome} respuesta={answer!r}")
    assert ok, answer


def test_eval_unknown_ticket_is_reported_as_not_found(counting, tmp_path):
    agent = make_agent(FakeBackend(), counting, tmp_path)
    run = agent.run("¿En qué estado está el ticket 9999?")
    trace = agent.trace_store.load(run.run_id)
    ok = (
        trace["status"] == STATUS_TOOL_FALLBACK
        and trace["sources_used"][0]["outcome"] == "not_found"
        and "No encuentro el ticket 9999" in trace["final_state"]["answer"]
        and counting.generations == 0
    )
    _record("fallback:ticket_not_found", ok, trace["final_state"]["answer"])
    assert ok


def test_eval_failed_tool_does_not_hide_the_rag_part_of_a_mixed_question(counting, tmp_path):
    agent = make_agent(FakeBackend(mode="timeout"), counting, tmp_path)
    run = agent.run(BOTH_QUESTION)
    trace = agent.trace_store.load(run.run_id)
    answer = trace["final_state"]["answer"]
    ok = (
        trace["status"] == STATUS_ANSWERED
        and [item["source"] for item in trace["sources_used"]] == ["tool:tickets", "rag"]
        and "Fuente: waste-protocol" in answer  # la parte de conocimiento (RAG) sí se respondió
        and "No pude confirmar el estado del ticket 12" in answer  # y se avisa de lo que no se pudo confirmar
    )
    _record("fallback:mixed_question_partial_answer", ok, f"respuesta={answer[-120:]!r}")
    assert ok


# --------------------------------------------------------------------------------------------------------------
# Eval 5 — las tools son de solo lectura (todas las peticiones del trace son GET, salvo el login)
# --------------------------------------------------------------------------------------------------------------
def test_eval_a_whole_run_only_reads(counting, tmp_path):
    backend = FakeBackend()
    agent = make_agent(backend, counting, tmp_path)
    for question in (TICKET_QUESTION, STOCK_QUESTION, BOTH_QUESTION):
        agent.run(question)
    writes = [call for call in backend.requests if call[0] != "GET" and call != ("POST", "/auth/login")]
    ok = writes == [] and ("GET", "/inventory/products") in backend.requests
    _record("read_only:no_writes_to_services", ok, f"peticiones={sorted(set(backend.requests))}")
    assert ok


# --------------------------------------------------------------------------------------------------------------
# Eval 6 (extra) — la tool de inventario sigue las mismas reglas: enrutamiento, timeout y fallback
# --------------------------------------------------------------------------------------------------------------
def test_eval_inventory_question_uses_the_inventory_tool(counting, tmp_path):
    backend = FakeBackend()
    agent = make_agent(backend, counting, tmp_path)
    trace = agent.trace_store.load(agent.run(STOCK_QUESTION).run_id)
    ok = (
        [item["source"] for item in trace["sources_used"]] == ["tool:inventory"]
        and counting.retrievals == 0
        and "Stock actual: 42" in trace["final_state"]["answer"]
    )
    _record("inventory:routing_and_data", ok, f"fuentes={trace['sources_used']}")
    assert ok


@pytest.mark.parametrize("mode", ["timeout", "down"])
def test_eval_inventory_failure_falls_back_honestly(counting, tmp_path, mode):
    agent = make_agent(FakeBackend(mode=mode), counting, tmp_path)
    trace = agent.trace_store.load(agent.run(STOCK_QUESTION).run_id)
    answer = trace["final_state"]["answer"]
    ok = (
        trace["status"] == STATUS_TOOL_FALLBACK
        and "No pude confirmar el stock del producto «pollo»" in answer
        and counting.generations == 0
    )
    _record(f"inventory:fallback_{mode}", ok, answer)
    assert ok, answer
