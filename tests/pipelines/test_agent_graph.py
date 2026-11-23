"""Pruebas del grafo del agente (LangGraph): estado, nodos, aristas, compilación, checkpointing, trace y errores.

Todo corre con dependencias simuladas (`SpyDependencies`): ni Qdrant ni modelos reales. Los evals que comprueban la
respuesta contra la base de conocimiento están en `test_agent_evals.py`.

    python -m pytest tests/pipelines/test_agent_graph.py
"""
from __future__ import annotations

import json
from typing import get_type_hints

import pytest
from agent_support import SpyDependencies, chunk
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from data.pipelines import rag as pipeline
from services.agent import graph as agent_graph
from services.agent import nodes
from services.agent.graph import AgentGraphError, build_checkpointer, build_graph, compile_graph
from services.agent.service import AgentExecutionError, AgentService
from services.agent.state import (
    STATUS_ANSWERED,
    STATUS_INVALID_QUESTION,
    STATUS_NO_INFORMATION,
    STATUS_RECEIVED,
    AgentState,
)
from services.agent.tracing import TraceStore


@pytest.fixture
def spy() -> SpyDependencies:
    return SpyDependencies()


@pytest.fixture
def service(spy, tmp_path) -> AgentService:
    return AgentService(spy.deps, checkpointer=InMemorySaver(), trace_store=TraceStore(tmp_path / "traces"))


# --------------------------------------------------------------------------------------------------------------
# Estado
# --------------------------------------------------------------------------------------------------------------
def test_state_is_minimal_and_has_no_conversation_history():
    # Parte 1: 4 campos. Parte 2 añade `route` y `tool_results` (los leen las aristas, la generación y el fallback).
    # Hito 8 añade los campos de memoria (los leen/escriben solo los nodos de memoria); sigue SIN haber historial
    # de mensajes: lo que el agente recuerda vive en el almacén de memoria, no en el estado.
    base = {"question", "context", "answer", "status", "route", "tool_results"}
    memory = {"conversation_id", "actor", "run_id", "memory_enabled", "memories", "proposal_raw", "memory_resolution",
              "memory_proposal"}
    assert set(get_type_hints(AgentState)) == base | memory


# --------------------------------------------------------------------------------------------------------------
# Nodos y aristas
# --------------------------------------------------------------------------------------------------------------
def test_receive_question_trims_and_validates():
    assert nodes.receive_question({"question": "  ¿Hola?  "}) == {"question": "¿Hola?", "status": STATUS_RECEIVED}
    for bad in ("", "   ", None, 5, "a" * (nodes.MAX_QUESTION_LENGTH + 1)):
        assert nodes.receive_question({"question": bad})["status"] == STATUS_INVALID_QUESTION


def test_reject_question_says_why():
    assert nodes.reject_question({"question": ""})["answer"] == nodes.EMPTY_QUESTION_ANSWER
    too_long = {"question": "a" * (nodes.MAX_QUESTION_LENGTH + 1)}
    assert nodes.reject_question(too_long)["answer"] == nodes.TOO_LONG_QUESTION_ANSWER


def test_routing_depends_on_the_state_not_on_a_fixed_sequence():
    assert nodes.route_after_receive({"status": STATUS_RECEIVED}) == nodes.ROUTE_ROUTE
    assert nodes.route_after_receive({"status": STATUS_INVALID_QUESTION}) == nodes.ROUTE_REJECT
    rag_only = {"route": {"sources": ["rag"]}}
    assert nodes.route_after_route(rag_only) == nodes.ROUTE_RETRIEVE
    assert nodes.route_after_retrieve({**rag_only, "context": [chunk("a", "b", "c")]}) == nodes.ROUTE_GENERATE
    assert nodes.route_after_retrieve({**rag_only, "context": []}) == nodes.ROUTE_NO_INFORMATION
    assert nodes.route_after_retrieve(rag_only) == nodes.ROUTE_NO_INFORMATION


def test_graph_has_the_expected_nodes_and_conditional_edges(service):
    drawable = service.graph.get_graph()
    assert set(drawable.nodes) - {"__start__", "__end__"} == set(nodes.NODE_NAMES)
    conditional = {(edge.source, edge.target) for edge in drawable.edges if edge.conditional}
    assert {(nodes.NODE_RECEIVE, nodes.NODE_ROUTE), (nodes.NODE_RECEIVE, nodes.NODE_REJECT)} <= conditional
    for source in (nodes.NODE_ROUTE, nodes.NODE_TICKETS, nodes.NODE_INVENTORY, nodes.NODE_RETRIEVE):
        assert {(source, nodes.NODE_GENERATE), (source, nodes.NODE_TOOL_FALLBACK),
                (source, nodes.NODE_NO_INFORMATION)} <= conditional
    assert {(nodes.NODE_ROUTE, nodes.NODE_TICKETS), (nodes.NODE_ROUTE, nodes.NODE_INVENTORY),
            (nodes.NODE_ROUTE, nodes.NODE_RETRIEVE), (nodes.NODE_TICKETS, nodes.NODE_RETRIEVE)} <= conditional


def test_answered_path_runs_each_step_once_and_hands_the_retrieved_context_to_generation(service, spy):
    run = service.run("  ¿Cuántos puntos para Oro?  ")
    assert run.status == STATUS_ANSWERED and run.answer == spy.answer
    assert spy.retrieve_calls == ["¿Cuántos puntos para Oro?"]  # la pregunta llega recortada
    assert spy.generate_calls == [("¿Cuántos puntos para Oro?", spy.context)]  # mismo contexto que produjo retrieve
    assert run.trace["node_order"] == [nodes.NODE_RECEIVE, nodes.NODE_ROUTE, nodes.NODE_RETRIEVE, nodes.NODE_GENERATE]


def test_without_context_the_agent_answers_honestly_and_never_calls_generation(tmp_path):
    spy = SpyDependencies(context=[])
    run = AgentService(spy.deps, checkpointer=InMemorySaver(), trace_store=TraceStore(tmp_path)).run("¿Capital de Francia?")
    assert run.status == STATUS_NO_INFORMATION and run.answer == nodes.NO_INFORMATION_ANSWER
    assert spy.generate_calls == []
    assert run.trace["node_order"] == [nodes.NODE_RECEIVE, nodes.NODE_ROUTE, nodes.NODE_RETRIEVE, nodes.NODE_NO_INFORMATION]


@pytest.mark.parametrize("question", ["", "   ", None])
def test_empty_question_is_rejected_before_any_retrieval(service, spy, question):
    run = service.run(question)
    assert run.status == STATUS_INVALID_QUESTION and run.answer == nodes.EMPTY_QUESTION_ANSWER
    assert spy.retrieve_calls == [] and spy.generate_calls == []
    assert run.trace["node_order"] == [nodes.NODE_RECEIVE, nodes.NODE_REJECT]


def test_nodes_reuse_the_rag_functions_and_never_the_monolithic_query(monkeypatch):
    deps = nodes.default_dependencies()
    assert deps.generate_fn is pipeline.generate_answer
    monkeypatch.setattr(pipeline, "retrieve", lambda question, **kw: [chunk("a", "b", "texto")])
    monkeypatch.setattr(pipeline, "generate_answer", lambda question, context: "ok")
    monkeypatch.setattr(pipeline, "query", lambda question: pytest.fail("ningún nodo debe llamar a query()"))
    rebuilt = nodes.default_dependencies()
    assert rebuilt.retrieve_fn("¿hola?") == [chunk("a", "b", "texto")]
    assert rebuilt.generate_fn("¿hola?", []) == "ok"


# --------------------------------------------------------------------------------------------------------------
# Compilación
# --------------------------------------------------------------------------------------------------------------
def test_a_valid_graph_compiles(spy):
    assert compile_graph(build_graph(spy.deps), InMemorySaver()) is not None


def test_compile_fails_clearly_for_an_unconnected_node(spy):
    builder = build_graph(spy.deps)
    builder.add_node("huerfano", lambda state: {})
    with pytest.raises(AgentGraphError, match="sin conexión.*huerfano"):
        compile_graph(builder)


def test_compile_fails_clearly_for_an_edge_to_a_missing_node():
    builder = StateGraph(AgentState)
    builder.add_node("a", lambda state: {})
    builder.add_edge(START, "a")
    builder.add_edge("a", "no_existe")
    with pytest.raises(AgentGraphError, match="no compila.*no_existe"):
        compile_graph(builder)


def test_compile_fails_clearly_without_an_entry_point():
    builder = StateGraph(AgentState)
    builder.add_node("a", lambda state: {})
    builder.add_edge("a", END)
    with pytest.raises(AgentGraphError, match="no compila"):
        compile_graph(builder)


def test_compile_fails_when_an_expected_node_is_missing():
    builder = StateGraph(AgentState)
    builder.add_node(nodes.NODE_RECEIVE, lambda state: {})
    builder.add_edge(START, nodes.NODE_RECEIVE)
    builder.add_edge(nodes.NODE_RECEIVE, END)
    with pytest.raises(AgentGraphError, match="faltan nodos"):
        compile_graph(builder)


def test_the_service_compiles_the_graph_when_it_is_created(spy, tmp_path, monkeypatch):
    def broken_build(deps, recorder_for=None):
        builder = StateGraph(AgentState)
        builder.add_node("a", lambda state: {})
        builder.add_edge(START, "a")
        builder.add_edge("a", "no_existe")
        return builder

    monkeypatch.setattr("services.agent.service.build_graph", broken_build)
    with pytest.raises(AgentGraphError):  # falla al crear el servicio, antes de cualquier petición
        AgentService(spy.deps, checkpointer=InMemorySaver(), trace_store=TraceStore(tmp_path))


# --------------------------------------------------------------------------------------------------------------
# Checkpointing
# --------------------------------------------------------------------------------------------------------------
def test_every_state_transition_leaves_a_checkpoint(service):
    run = service.run("¿Cuántos puntos para Oro?")
    config = {"configurable": {"thread_id": run.run_id}}
    history = list(service.graph.get_state_history(config))
    assert len(history) >= 4  # entrada + una por cada nodo ejecutado
    assert service.graph.get_state(config).values["status"] == STATUS_ANSWERED
    checkpoints = run.trace["checkpoints"]
    assert len(checkpoints) == len(history)
    assert len({item["checkpoint_id"] for item in checkpoints}) == len(checkpoints)
    assert any(item["next"] == [nodes.NODE_GENERATE] for item in checkpoints)  # estado justo antes de generar


def test_a_run_can_be_resumed_from_its_checkpoint_without_repeating_retrieval(service, spy):
    run = service.run("¿Cuántos puntos para Oro?")
    config = {"configurable": {"thread_id": run.run_id}}
    before_generation = next(
        snapshot for snapshot in service.graph.get_state_history(config) if snapshot.next == (nodes.NODE_GENERATE,)
    )
    assert before_generation.values["context"] == spy.context
    resumed = service.graph.invoke(None, before_generation.config)
    assert resumed["status"] == STATUS_ANSWERED
    assert len(spy.retrieve_calls) == 1 and len(spy.generate_calls) == 2  # solo se repite la generación


def test_checkpoints_can_survive_a_restart_with_sqlite(spy, tmp_path):
    database = str(tmp_path / "checkpoints.sqlite")
    first = AgentService(spy.deps, checkpointer=build_checkpointer(database), trace_store=TraceStore(tmp_path / "t"))
    run = first.run("¿Cuántos puntos para Oro?")
    second = AgentService(spy.deps, checkpointer=build_checkpointer(database), trace_store=TraceStore(tmp_path / "t"))
    config = {"configurable": {"thread_id": run.run_id}}
    assert second.graph.get_state(config).values["answer"] == spy.answer


def test_default_checkpointer_is_in_memory_unless_a_database_is_configured(monkeypatch):
    monkeypatch.delenv("AGENT_CHECKPOINT_DB", raising=False)
    assert isinstance(build_checkpointer(), InMemorySaver)
    assert agent_graph.InMemorySaver is InMemorySaver


# --------------------------------------------------------------------------------------------------------------
# Trace
# --------------------------------------------------------------------------------------------------------------
def test_every_run_saves_a_trace_that_can_be_read_afterwards(service):
    run = service.run("¿Cuántos puntos para Oro?")
    saved = service.trace_store.load(run.run_id)
    assert saved["run_id"] == run.run_id and saved["status"] == STATUS_ANSWERED
    assert [step["node"] for step in saved["steps"]] == saved["node_order"]
    assert [step["order"] for step in saved["steps"]] == [1, 2, 3, 4]
    retrieve_step = saved["steps"][2]
    assert retrieve_step["output"]["context"] == [
        {"source_document": "loyalty-program", "section": "Niveles", "chunk_index": 0}
    ]  # referencias, no el texto de los documentos
    assert all(step["duration_ms"] >= 0 and step["error"] is None for step in saved["steps"])
    assert saved["final_state"]["answer"] == run.answer
    json.dumps(saved)  # se puede serializar tal cual


def test_a_failing_node_is_recorded_in_the_trace_and_reported_with_its_run_id(tmp_path):
    spy = SpyDependencies()

    def boom(question, context):
        raise RuntimeError("secreto-interno")

    store = TraceStore(tmp_path)
    failing = AgentService(
        type(spy.deps)(retrieve_fn=spy.retrieve, generate_fn=boom), checkpointer=InMemorySaver(), trace_store=store
    )
    with pytest.raises(AgentExecutionError) as caught:
        failing.run("¿Cuántos puntos para Oro?")
    saved = store.load(caught.value.run_id)
    assert saved["status"] == "error" and saved["error"]["type"] == "RuntimeError"
    assert saved["steps"][-1]["node"] == nodes.NODE_GENERATE and "secreto-interno" in saved["steps"][-1]["error"]
    assert saved["node_order"] == [nodes.NODE_RECEIVE, nodes.NODE_ROUTE, nodes.NODE_RETRIEVE, nodes.NODE_GENERATE]


def test_trace_store_lists_runs_and_rejects_unsafe_ids(service, tmp_path):
    run = service.run("¿Cuántos puntos para Oro?")
    assert service.trace_store.list_runs() == [run.run_id]
    for unsafe in ("../secreto", "a/b", "", "x" * 100):
        with pytest.raises(ValueError):
            service.trace_store.load(unsafe)
    assert TraceStore(tmp_path / "vacio").list_runs() == []
