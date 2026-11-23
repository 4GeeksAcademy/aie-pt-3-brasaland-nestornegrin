"""Construcción y compilación del grafo del agente.

    START -> receive_question --(válida)--> route_question --(según la pregunta; en este orden)-->
                  |                                  lookup_tickets? -> lookup_inventory? -> retrieve_context?
                  |                                                                  |
                  +--(vacía o larga)--> reject_question -> END          (hay evidencia)  -> generate_answer  -> END
                                                                        (una tool falló) -> tool_fallback   -> END
                                                                        (RAG sin nada)   -> no_information  -> END

Las aristas que salen de `receive_question`, `route_question` y de cada nodo de recopilación son CONDICIONALES (decide
una función sobre el estado, con las salidas declaradas), no una secuencia fija: el enrutador elige entre RAG, tool de
tickets, tool de inventario o varias a la vez, y el final depende de si hay evidencia o de si una tool falló. El grafo se
compila siempre de forma explícita con `compile_graph()` antes de ejecutar nada: un nodo sin conexión, una arista a un
nodo que no existe o la falta de un nodo esperado se detectan al arrancar el servicio, con un `AgentGraphError` claro.
"""
from __future__ import annotations

import os
import sqlite3
from typing import Callable

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from .nodes import (
    NODE_GENERATE,
    NODE_INVENTORY,
    NODE_NAMES,
    NODE_NO_INFORMATION,
    NODE_RECEIVE,
    NODE_REJECT,
    NODE_RETRIEVE,
    NODE_ROUTE,
    NODE_TICKETS,
    NODE_TOOL_FALLBACK,
    ROUTE_CASUAL as ROUTE_NO_EVIDENCE_CASUAL,
    ROUTE_GENERATE,
    ROUTE_INVENTORY,
    ROUTE_NO_INFORMATION,
    ROUTE_REJECT,
    ROUTE_RETRIEVE,
    ROUTE_ROUTE,
    ROUTE_TICKETS,
    ROUTE_TOOL_FALLBACK,
    AgentDependencies,
    make_generate_node,
    make_inventory_node,
    make_retrieve_node,
    make_route_node,
    make_tickets_node,
    no_information,
    receive_question,
    reject_question,
    route_after_inventory,
    route_after_receive,
    route_after_retrieve,
    route_after_route,
    route_after_tickets,
    tool_fallback,
)
from .guardrail_nodes import (
    GUARD_NODE_NAMES,
    NODE_CASUAL,
    NODE_INPUT_GUARD,
    NODE_ISOLATE,
    NODE_OUTPUT_GUARD,
    NODE_REFUSE,
    ROUTE_BLOCK,
    ROUTE_CASUAL,
    ROUTE_CONTINUE,
    ROUTE_END,
    ROUTE_PROPOSE,
    make_casual_node,
    make_input_guard_node,
    make_isolate_node,
    make_output_guard_node,
    make_route_after_output,
    refuse_request,
    route_after_input_guard,
)
from .memory_nodes import (
    MEMORY_NODE_NAMES,
    NODE_MEMORY_ACK,
    NODE_PROPOSE,
    NODE_RECALL,
    NODE_RESOLVE,
    ROUTE_ACK,
    acknowledge_memory,
    make_memory_generate_node,
    make_propose_node,
    make_recall_node,
    make_resolve_node,
    route_after_resolve,
)
from .state import AgentState
from .tracing import TraceRecorder, traced_node


class AgentGraphError(RuntimeError):
    """El grafo del agente no se pudo compilar o le falta alguno de los nodos esperados."""


def build_graph(
    deps: AgentDependencies,
    recorder_for: Callable[[str], TraceRecorder | None] = lambda run_id: None,
) -> StateGraph:
    """Define nodos y aristas (sin compilar). `recorder_for(run_id)` devuelve el recorder del trace de esa corrida.

    Con `deps.memory` se añaden los nodos de memoria (ver `memory_nodes.py`):
        receive -> resolve_pending -> (solo era la respuesta a la propuesta) acknowledge_memory -> END
                                   -> route_question -> recall_memory -> fuentes... -> generate_answer -> propose_memory -> END
    Sin `deps.memory` el grafo es el de siempre."""
    memory = deps.memory is not None
    guard = deps.guardrails is not None
    builder = StateGraph(AgentState)

    nodes = {
        NODE_RECEIVE: receive_question,
        NODE_ROUTE: make_route_node(deps),
        NODE_TICKETS: make_tickets_node(deps),
        NODE_INVENTORY: make_inventory_node(deps),
        NODE_RETRIEVE: make_retrieve_node(deps),
        NODE_GENERATE: make_memory_generate_node(deps) if memory else make_generate_node(deps),
        NODE_NO_INFORMATION: no_information,
        NODE_TOOL_FALLBACK: tool_fallback,
        NODE_REJECT: reject_question,
    }
    for name, function in nodes.items():
        builder.add_node(name, traced_node(name, function, recorder_for))

    # Salidas posibles al terminar de recopilar (las comparten todos los nodos de recopilación).
    finish = {ROUTE_GENERATE: NODE_GENERATE, ROUTE_TOOL_FALLBACK: NODE_TOOL_FALLBACK,
              ROUTE_NO_INFORMATION: NODE_NO_INFORMATION}
    if guard:  # con guardrails, lo que se genera pasa antes por el aislamiento del contenido externo
        finish[ROUTE_GENERATE] = NODE_ISOLATE
        finish[ROUTE_NO_EVIDENCE_CASUAL] = NODE_CASUAL
    sources = {ROUTE_TICKETS: NODE_TICKETS, ROUTE_INVENTORY: NODE_INVENTORY, ROUTE_RETRIEVE: NODE_RETRIEVE}

    if memory:
        for name, function in {NODE_RESOLVE: make_resolve_node(deps), NODE_MEMORY_ACK: acknowledge_memory,
                               NODE_RECALL: make_recall_node(deps), NODE_PROPOSE: make_propose_node(deps)}.items():
            builder.add_node(name, traced_node(name, function, recorder_for))

    first = NODE_RESOLVE if memory else NODE_ROUTE
    if guard:
        for name, function in {NODE_INPUT_GUARD: make_input_guard_node(deps), NODE_REFUSE: refuse_request,
                               NODE_CASUAL: make_casual_node(deps), NODE_ISOLATE: make_isolate_node(deps),
                               NODE_OUTPUT_GUARD: make_output_guard_node(deps)}.items():
            builder.add_node(name, traced_node(name, function, recorder_for))

    builder.add_edge(START, NODE_RECEIVE)
    builder.add_conditional_edges(
        NODE_RECEIVE, route_after_receive, {ROUTE_ROUTE: NODE_INPUT_GUARD if guard else first, ROUTE_REJECT: NODE_REJECT})
    if guard:
        builder.add_conditional_edges(
            NODE_INPUT_GUARD, route_after_input_guard,
            {ROUTE_CONTINUE: first, ROUTE_BLOCK: NODE_REFUSE, ROUTE_CASUAL: NODE_CASUAL})
        builder.add_edge(NODE_ISOLATE, NODE_GENERATE)
    if memory:
        builder.add_conditional_edges(NODE_RESOLVE, route_after_resolve, {ROUTE_ROUTE: NODE_ROUTE, ROUTE_ACK: NODE_MEMORY_ACK})
        builder.add_edge(NODE_ROUTE, NODE_RECALL)
        builder.add_conditional_edges(NODE_RECALL, route_after_route, {**sources, **finish})
    else:
        builder.add_conditional_edges(NODE_ROUTE, route_after_route, {**sources, **finish})
    builder.add_conditional_edges(
        NODE_TICKETS, route_after_tickets,
        {ROUTE_INVENTORY: NODE_INVENTORY, ROUTE_RETRIEVE: NODE_RETRIEVE, **finish})
    builder.add_conditional_edges(NODE_INVENTORY, route_after_inventory, {ROUTE_RETRIEVE: NODE_RETRIEVE, **finish})
    builder.add_conditional_edges(NODE_RETRIEVE, route_after_retrieve, finish)
    terminals = [NODE_REJECT]
    if guard:
        terminals.append(NODE_REFUSE)
        # La respuesta del modelo (y la del small talk) se valida antes de entregarla y, con memoria, antes de proponer.
        builder.add_edge(NODE_CASUAL, NODE_OUTPUT_GUARD)
        builder.add_conditional_edges(NODE_OUTPUT_GUARD, make_route_after_output(deps),
                                      {ROUTE_PROPOSE: NODE_PROPOSE, ROUTE_END: END} if memory else {ROUTE_END: END})
    if memory:
        # Toda respuesta con contenido pasa por `propose_memory`: antepone lo que pasó con la propuesta anterior (si el
        # usuario la contestó y además preguntó otra cosa) y añade la propuesta nueva (si el modelo la hizo y la política la acepta).
        for answering in (NODE_NO_INFORMATION, NODE_TOOL_FALLBACK) + (() if guard else (NODE_GENERATE,)):
            builder.add_edge(answering, NODE_PROPOSE)
        if guard:
            builder.add_edge(NODE_GENERATE, NODE_OUTPUT_GUARD)
        terminals += [NODE_PROPOSE, NODE_MEMORY_ACK]
    else:
        terminals += [NODE_NO_INFORMATION, NODE_TOOL_FALLBACK] + ([] if guard else [NODE_GENERATE])
        if guard:
            builder.add_edge(NODE_GENERATE, NODE_OUTPUT_GUARD)
    for terminal in terminals:
        builder.add_edge(terminal, END)
    return builder


def _reachable(start: str, links: dict[str, set[str]]) -> set[str]:
    seen, pending = {start}, [start]
    while pending:
        for neighbour in links.get(pending.pop(), ()):
            if neighbour not in seen:
                seen.add(neighbour)
                pending.append(neighbour)
    return seen


def check_connectivity(compiled) -> None:
    """LangGraph compila un nodo huérfano o sin salida sin protestar; aquí se exige que TODO nodo sea alcanzable
    desde START y que desde TODO nodo se pueda llegar a END (un nodo sin conexión es un error estructural)."""
    drawable = compiled.get_graph()
    forward: dict[str, set[str]] = {}
    backward: dict[str, set[str]] = {}
    for edge in drawable.edges:
        forward.setdefault(edge.source, set()).add(edge.target)
        backward.setdefault(edge.target, set()).add(edge.source)
    names = {name for name in drawable.nodes if name not in ("__start__", "__end__")}
    unreachable = names - _reachable("__start__", forward)
    dead_ends = names - _reachable("__end__", backward)
    if unreachable:
        raise AgentGraphError(f"Nodos sin conexión desde el inicio del grafo: {sorted(unreachable)}")
    if dead_ends:
        raise AgentGraphError(f"Nodos sin salida hacia el final del grafo: {sorted(dead_ends)}")


def compile_graph(builder: StateGraph, checkpointer=None):
    """Compila el grafo y comprueba su estructura. Falla con `AgentGraphError` y un motivo claro."""
    try:
        compiled = builder.compile(checkpointer=checkpointer)
    except Exception as error:  # noqa: BLE001 - LangGraph lanza ValueError con el motivo estructural
        raise AgentGraphError(f"El grafo del agente no compila: {error}") from error
    check_connectivity(compiled)
    present = compiled.get_graph().nodes
    expected = (set(NODE_NAMES) | (set(MEMORY_NODE_NAMES) if "resolve_pending" in present else set())
                | (set(GUARD_NODE_NAMES) if "input_guard" in present else set()))
    missing = expected - set(compiled.get_graph().nodes)
    if missing:
        raise AgentGraphError(f"Al grafo del agente le faltan nodos: {sorted(missing)}")
    return compiled


def build_checkpointer(sqlite_path: str | None = None):
    """Dónde se guardan los checkpoints de cada corrida.

    Por defecto, en memoria (suficiente para inspeccionar corridas del proceso en curso). Con `AGENT_CHECKPOINT_DB`
    (o el argumento) se guardan en un archivo SQLite y sobreviven a un reinicio, de modo que una corrida se puede
    inspeccionar o retomar después con su `thread_id` (= `run_id`)."""
    path = sqlite_path or os.environ.get("AGENT_CHECKPOINT_DB")
    if not path:
        return InMemorySaver()
    from langgraph.checkpoint.sqlite import SqliteSaver

    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))
