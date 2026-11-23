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
from .state import AgentState
from .tracing import TraceRecorder, traced_node


class AgentGraphError(RuntimeError):
    """El grafo del agente no se pudo compilar o le falta alguno de los nodos esperados."""


def build_graph(
    deps: AgentDependencies,
    recorder_for: Callable[[str], TraceRecorder | None] = lambda run_id: None,
) -> StateGraph:
    """Define nodos y aristas (sin compilar). `recorder_for(run_id)` devuelve el recorder del trace de esa corrida."""
    builder = StateGraph(AgentState)

    nodes = {
        NODE_RECEIVE: receive_question,
        NODE_ROUTE: make_route_node(deps),
        NODE_TICKETS: make_tickets_node(deps),
        NODE_INVENTORY: make_inventory_node(deps),
        NODE_RETRIEVE: make_retrieve_node(deps),
        NODE_GENERATE: make_generate_node(deps),
        NODE_NO_INFORMATION: no_information,
        NODE_TOOL_FALLBACK: tool_fallback,
        NODE_REJECT: reject_question,
    }
    for name, function in nodes.items():
        builder.add_node(name, traced_node(name, function, recorder_for))

    # Salidas posibles al terminar de recopilar (las comparten todos los nodos de recopilación).
    finish = {ROUTE_GENERATE: NODE_GENERATE, ROUTE_TOOL_FALLBACK: NODE_TOOL_FALLBACK,
              ROUTE_NO_INFORMATION: NODE_NO_INFORMATION}
    sources = {ROUTE_TICKETS: NODE_TICKETS, ROUTE_INVENTORY: NODE_INVENTORY, ROUTE_RETRIEVE: NODE_RETRIEVE}

    builder.add_edge(START, NODE_RECEIVE)
    builder.add_conditional_edges(NODE_RECEIVE, route_after_receive, {ROUTE_ROUTE: NODE_ROUTE, ROUTE_REJECT: NODE_REJECT})
    builder.add_conditional_edges(NODE_ROUTE, route_after_route, {**sources, **finish})
    builder.add_conditional_edges(
        NODE_TICKETS, route_after_tickets,
        {ROUTE_INVENTORY: NODE_INVENTORY, ROUTE_RETRIEVE: NODE_RETRIEVE, **finish})
    builder.add_conditional_edges(NODE_INVENTORY, route_after_inventory, {ROUTE_RETRIEVE: NODE_RETRIEVE, **finish})
    builder.add_conditional_edges(NODE_RETRIEVE, route_after_retrieve, finish)
    for terminal in (NODE_GENERATE, NODE_NO_INFORMATION, NODE_TOOL_FALLBACK, NODE_REJECT):
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
    missing = set(NODE_NAMES) - set(compiled.get_graph().nodes)
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
