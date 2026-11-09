"""Construcción y compilación del grafo del agente.

    START -> receive_question --(pregunta válida)--> retrieve_context --(hay contexto)--> generate_answer -> END
                  |                                        |
                  +--(vacía o demasiado larga)--> reject_question -> END
                                                           +--(nada supera el umbral)--> no_information -> END

Las aristas que salen de `receive_question` y de `retrieve_context` son CONDICIONALES (decide una función sobre el
estado, con las salidas declaradas), no una secuencia fija. El grafo se compila siempre de forma explícita con
`compile_graph()` antes de ejecutar nada: un nodo sin conexión, una arista a un nodo que no existe o la falta de un
nodo esperado se detectan al arrancar el servicio, con un `AgentGraphError` claro, y no en la primera petición real.
"""
from __future__ import annotations

import os
import sqlite3
from typing import Callable

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from .nodes import (
    NODE_GENERATE,
    NODE_NAMES,
    NODE_NO_INFORMATION,
    NODE_RECEIVE,
    NODE_REJECT,
    NODE_RETRIEVE,
    ROUTE_GENERATE,
    ROUTE_NO_INFORMATION,
    ROUTE_REJECT,
    ROUTE_RETRIEVE,
    AgentDependencies,
    make_generate_node,
    make_retrieve_node,
    no_information,
    receive_question,
    reject_question,
    route_after_receive,
    route_after_retrieve,
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
        NODE_RETRIEVE: make_retrieve_node(deps),
        NODE_GENERATE: make_generate_node(deps),
        NODE_NO_INFORMATION: no_information,
        NODE_REJECT: reject_question,
    }
    for name, function in nodes.items():
        builder.add_node(name, traced_node(name, function, recorder_for))

    builder.add_edge(START, NODE_RECEIVE)
    builder.add_conditional_edges(
        NODE_RECEIVE,
        route_after_receive,
        {ROUTE_RETRIEVE: NODE_RETRIEVE, ROUTE_REJECT: NODE_REJECT},
    )
    builder.add_conditional_edges(
        NODE_RETRIEVE,
        route_after_retrieve,
        {ROUTE_GENERATE: NODE_GENERATE, ROUTE_NO_INFORMATION: NODE_NO_INFORMATION},
    )
    for terminal in (NODE_GENERATE, NODE_NO_INFORMATION, NODE_REJECT):
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
