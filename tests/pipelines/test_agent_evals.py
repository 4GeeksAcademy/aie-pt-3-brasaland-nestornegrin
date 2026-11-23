"""Evals del agente LangGraph: cada comprobación se hace sobre el TRACE de la corrida, no sobre la consola.

Corren sin red ni claves: la base de conocimiento REAL (docs/company-knowledge-base) se indexa en un Qdrant en memoria
con un embedding falso, y el modelo de chat se sustituye por un generador extractivo determinista. Así se evalúa la
lógica del agente (rutas, contexto, anclaje en el BRIEFING) sin depender de un modelo.

    python -m pytest tests/pipelines/test_agent_evals.py          # un solo comando
    python -m pytest tests/pipelines                              # todo, incluidos los tests RAG existentes

Con `AGENT_EVAL_RESULTS=ruta.json` se guarda además un resumen de resultados (lo usa el PR como evidencia).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from agent_support import extractive_generate, fake_embed
from langgraph.checkpoint.memory import InMemorySaver
from qdrant_client import QdrantClient

from data.pipelines import rag as pipeline
from data.process import rag as process
from data.process import rag_config
from services.agent import nodes
from services.agent.nodes import AgentDependencies
from services.agent.service import AgentService
from services.agent.state import STATUS_ANSWERED, STATUS_INVALID_QUESTION, STATUS_NO_INFORMATION
from services.agent.tracing import TraceStore

FAKE_MIN_SCORE = 0.30  # calibrado para el embedding falso (el real usa RAG_MIN_SCORE)
DOCS_DIR = rag_config.KNOWLEDGE_BASE_DIR

# (id, pregunta, documento esperado, dato que debe aparecer en la respuesta Y en el documento fuente)
ANCHORED_CASES = [
    ("oro", "¿Cuántos puntos hay que acumular para el nivel Oro y qué descuento permanente da?",
     "loyalty-program", "50+ puntos"),
    ("merma", "¿Cuándo hay que escribir una nota explicativa por desperdicio de proteína cárnica en un solo turno?",
     "waste-protocol", "2 kg"),
    ("proveedores", "¿Qué día y a qué hora se genera el pedido semanal a proveedores?",
     "supplier-ordering", "10:00"),
    ("gluten", "¿Hay versión sin gluten certificada de las Costillas BBQ?",
     "menu-allergens", "No existe versión sin gluten certificada"),
]
OUT_OF_SCOPE = "¿Cuál es la capital de Francia?"

_RESULTS: list[dict] = []


@pytest.fixture(scope="module")
def knowledge_client() -> QdrantClient:
    client = QdrantClient(":memory:")
    process.setup(client=client, embed_fn=fake_embed)
    return client


@pytest.fixture
def agent(knowledge_client, tmp_path) -> AgentService:
    deps = AgentDependencies(
        retrieve_fn=lambda question: pipeline.retrieve(
            question, min_score=FAKE_MIN_SCORE, client=knowledge_client, embed_fn=fake_embed
        ),
        generate_fn=extractive_generate,
    )
    return AgentService(deps, checkpointer=InMemorySaver(), trace_store=TraceStore(tmp_path / "traces"))


def _record(name: str, passed: bool, detail: str) -> None:
    _RESULTS.append({"eval": name, "passed": passed, "detail": detail})


def _doc_text(source: str) -> str:
    return next(p for p in Path(DOCS_DIR).glob("*.es.md") if source in p.name).read_text(encoding="utf-8")


@pytest.fixture(scope="module", autouse=True)
def _save_results():
    yield
    target = os.environ.get("AGENT_EVAL_RESULTS")
    if target:
        Path(target).write_text(json.dumps({"results": _RESULTS}, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------------------------------------------
# Eval 1 — respuestas ancladas en la base de conocimiento (BRIEFING)
# --------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("case_id, question, source, fact", ANCHORED_CASES, ids=[c[0] for c in ANCHORED_CASES])
def test_eval_answer_is_anchored_in_the_knowledge_base(agent, case_id, question, source, fact):
    run = agent.run(question)
    trace = agent.trace_store.load(run.run_id)

    retrieved = trace["steps"][1]["output"]["context"]  # lo que recuperó, según el trace
    retrieved_sources = {item["source_document"] for item in retrieved}
    ok = (
        trace["status"] == STATUS_ANSWERED
        and source in retrieved_sources
        and fact in trace["final_state"]["answer"]
        and fact in _doc_text(source)  # el dato existe de verdad en el documento fuente
        and f"Fuente: {source}" in trace["final_state"]["answer"]
    )
    _record(f"anchored:{case_id}", ok, f"fuentes={sorted(retrieved_sources)} dato='{fact}'")
    assert ok, f"{case_id}: respuesta no anclada en {source}. Trace: {trace['node_order']}, fuentes {retrieved_sources}"


# --------------------------------------------------------------------------------------------------------------
# Eval 2 — sin contexto sobre el umbral: respuesta honesta y NO se genera
# --------------------------------------------------------------------------------------------------------------
def test_eval_out_of_scope_question_is_answered_honestly_without_generation(agent):
    run = agent.run(OUT_OF_SCOPE)
    trace = agent.trace_store.load(run.run_id)
    ok = (
        trace["status"] == STATUS_NO_INFORMATION
        and nodes.NODE_GENERATE not in trace["node_order"]
        and trace["node_order"] == [nodes.NODE_RECEIVE, nodes.NODE_RETRIEVE, nodes.NODE_NO_INFORMATION]
        and trace["final_state"]["answer"] == nodes.NO_INFORMATION_ANSWER
        and trace["steps"][1]["output"]["context"] == []
    )
    _record("no_information_without_generation", ok, f"ruta={trace['node_order']}")
    assert ok


# --------------------------------------------------------------------------------------------------------------
# Eval 3 — pregunta vacía: error claro, sin recuperar ni generar
# --------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("question", ["", "   \n\t "])
def test_eval_empty_question_ends_with_a_clear_error_and_touches_nothing(agent, question):
    run = agent.run(question)
    trace = agent.trace_store.load(run.run_id)
    ok = (
        trace["status"] == STATUS_INVALID_QUESTION
        and trace["node_order"] == [nodes.NODE_RECEIVE, nodes.NODE_REJECT]
        and trace["final_state"]["answer"] == nodes.EMPTY_QUESTION_ANSWER
    )
    _record(f"empty_question:{question!r}", ok, f"ruta={trace['node_order']}")
    assert ok


# --------------------------------------------------------------------------------------------------------------
# Eval 4 — consistencia del trace: cada corrida es consultable y coherente con sus checkpoints
# --------------------------------------------------------------------------------------------------------------
def test_eval_trace_is_complete_and_consistent_with_checkpoints(agent):
    run = agent.run(ANCHORED_CASES[0][1])
    trace = agent.trace_store.load(run.run_id)
    ok = (
        trace["run_id"] == run.run_id
        and trace["finished_at"] and trace["duration_ms"] >= 0
        and [s["node"] for s in trace["steps"]] == trace["node_order"]
        and all(s["error"] is None for s in trace["steps"])
        and len(trace["checkpoints"]) >= len(trace["node_order"]) + 1
        and trace["checkpoints"][-1]["next"] == []  # el último checkpoint ya no tiene nodos pendientes
    )
    _record("trace_consistency", ok, f"nodos={trace['node_order']} checkpoints={len(trace['checkpoints'])}")
    assert ok


# --------------------------------------------------------------------------------------------------------------
# Eval 5 — la generación recibe exactamente el contexto que recuperó retrieve (sin duplicar ni inventar)
# --------------------------------------------------------------------------------------------------------------
def test_eval_generation_receives_exactly_the_retrieved_context(knowledge_client, tmp_path):
    seen: dict = {}

    def spying_generate(question, context):
        seen["context"] = context
        return extractive_generate(question, context)

    retrieved_holder: dict = {}

    def spying_retrieve(question):
        retrieved_holder["context"] = pipeline.retrieve(
            question, min_score=FAKE_MIN_SCORE, client=knowledge_client, embed_fn=fake_embed
        )
        return retrieved_holder["context"]

    service = AgentService(AgentDependencies(spying_retrieve, spying_generate),
                           checkpointer=InMemorySaver(), trace_store=TraceStore(tmp_path))
    run = service.run(ANCHORED_CASES[1][1])
    ok = run.status == STATUS_ANSWERED and seen["context"] == retrieved_holder["context"] and seen["context"]
    _record("generation_gets_retrieved_context", bool(ok), f"{len(seen.get('context', []))} fragmentos")
    assert ok
