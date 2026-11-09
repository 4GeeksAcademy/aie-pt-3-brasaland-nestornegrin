"""Nodos del grafo y funciones de enrutamiento (aristas condicionales).

Cada nodo hace UNA cosa y devuelve solo las claves del estado que cambia:

    receive_question   valida y normaliza la pregunta
    route_question     decide qué fuentes hacen falta (RAG, tool de tickets, tool de inventario) a partir de la pregunta
    lookup_tickets     llama a la tool de tickets (gestor de incidentes real, solo lectura)
    lookup_inventory   llama a la tool de inventario (gestor de inventario real, solo lectura)
    retrieve_context   llama a `retrieve()` (data/pipelines/rag.py)
    generate_answer    llama a `generate_answer(question, context)` con las evidencias que YA produjeron los nodos anteriores
    no_information     responde con honestidad cuando no se recuperó nada (sin llamar al modelo)
    tool_fallback      responde con honestidad cuando la tool falló o el recurso no existe (sin llamar al modelo)
    reject_question    devuelve un mensaje claro cuando la pregunta no es válida

Ningún nodo llama a `query()`: eso volvería a ejecutar la recuperación dentro de la generación y taparía justo el
flujo que este grafo hace visible. Las dependencias entran por `AgentDependencies` para poder probar el grafo sin
Qdrant ni modelos reales.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .routing import SOURCE_INVENTORY, SOURCE_ORDER, SOURCE_RAG, SOURCE_TICKETS, RoutePlan, plan_route
from .state import (
    STATUS_ANSWERED,
    STATUS_INVALID_QUESTION,
    STATUS_NO_INFORMATION,
    STATUS_RECEIVED,
    STATUS_TOOL_FALLBACK,
    AgentState,
)
from .tools import (
    InventoryQuery,
    InventoryResult,
    TicketQuery,
    TicketsResult,
    ToolOutcome,
)

# Nombres de nodos (no pueden coincidir con claves del estado: LangGraph lo rechaza).
NODE_RECEIVE = "receive_question"
NODE_ROUTE = "route_question"
NODE_TICKETS = "lookup_tickets"
NODE_INVENTORY = "lookup_inventory"
NODE_RETRIEVE = "retrieve_context"
NODE_GENERATE = "generate_answer"
NODE_NO_INFORMATION = "no_information"
NODE_REJECT = "reject_question"
NODE_TOOL_FALLBACK = "tool_fallback"
NODE_NAMES = (
    NODE_RECEIVE, NODE_ROUTE, NODE_TICKETS, NODE_INVENTORY, NODE_RETRIEVE,
    NODE_GENERATE, NODE_NO_INFORMATION, NODE_TOOL_FALLBACK, NODE_REJECT,
)
# Fuente de datos de cada nodo de recopilación (para el trace y para el enrutamiento).
NODE_BY_SOURCE = {SOURCE_TICKETS: NODE_TICKETS, SOURCE_INVENTORY: NODE_INVENTORY, SOURCE_RAG: NODE_RETRIEVE}

# Nombres de las salidas de las aristas condicionales.
ROUTE_ROUTE = "route"  # pregunta válida -> enrutador
ROUTE_REJECT = "reject"
ROUTE_TICKETS = SOURCE_TICKETS
ROUTE_INVENTORY = SOURCE_INVENTORY
ROUTE_RETRIEVE = SOURCE_RAG
ROUTE_GENERATE = "generate"
ROUTE_NO_INFORMATION = "no_information"
ROUTE_TOOL_FALLBACK = "tool_fallback"

MAX_QUESTION_LENGTH = 1000
NO_INFORMATION_ANSWER = "No tengo información suficiente en la base de conocimiento de Brasaland para responder eso."
EMPTY_QUESTION_ANSWER = "La pregunta no puede estar vacía."
TOO_LONG_QUESTION_ANSWER = f"La pregunta no puede superar los {MAX_QUESTION_LENGTH} caracteres."


@dataclass(frozen=True)
class AgentDependencies:
    """Funciones que usan los nodos. Las tools son opcionales: sin ellas, el nodo responde que no están disponibles."""

    retrieve_fn: Callable[[str], list[dict]]
    generate_fn: Callable[[str, list[dict]], str]
    ticket_fn: Callable[[TicketQuery], TicketsResult] | None = None
    inventory_fn: Callable[[InventoryQuery], InventoryResult] | None = None
    router_fn: Callable[[str], RoutePlan] = plan_route


def default_dependencies() -> AgentDependencies:
    """El RAG real (reutilizado desde `data/pipelines/rag.py`, sin copiarlo) y las tools que consumen el servidor MCP."""
    from data.pipelines.rag import generate_answer, retrieve

    from .mcp_tools import McpGateway, McpInventoryTool, McpTicketTool

    gateway = McpGateway()  # único camino a los datos operativos: el servidor MCP (no hay acceso directo al backend)
    return AgentDependencies(
        retrieve_fn=lambda question: retrieve(question),
        generate_fn=generate_answer,
        ticket_fn=McpTicketTool(gateway),
        inventory_fn=McpInventoryTool(gateway),
    )


# --------------------------------------------------------------------------------------------------------------
# Nodos
# --------------------------------------------------------------------------------------------------------------
def receive_question(state: AgentState) -> dict:
    raw = state.get("question")
    question = raw.strip() if isinstance(raw, str) else ""
    if not question or len(question) > MAX_QUESTION_LENGTH:
        return {"question": question, "status": STATUS_INVALID_QUESTION}
    return {"question": question, "status": STATUS_RECEIVED}


def reject_question(state: AgentState) -> dict:
    question = state.get("question") or ""
    answer = TOO_LONG_QUESTION_ANSWER if len(question) > MAX_QUESTION_LENGTH else EMPTY_QUESTION_ANSWER
    return {"answer": answer, "status": STATUS_INVALID_QUESTION}


def make_retrieve_node(deps: AgentDependencies) -> Callable[[AgentState], dict]:
    def retrieve_context(state: AgentState) -> dict:
        return {"context": deps.retrieve_fn(state["question"])}

    return retrieve_context


def route_question(state: AgentState, deps: AgentDependencies) -> dict:
    return {"route": deps.router_fn(state["question"]).to_dict()}


def make_route_node(deps: AgentDependencies) -> Callable[[AgentState], dict]:
    def route_question_node(state: AgentState) -> dict:
        return route_question(state, deps)

    return route_question_node


_UNAVAILABLE = {"outcome": ToolOutcome.UNAVAILABLE.value, "error": "La tool no está configurada en este agente."}


def _tool_entry(tool: str, outcome: str, result: dict) -> dict:
    return {"tool": tool, "outcome": outcome, "result": result}


def make_tickets_node(deps: AgentDependencies) -> Callable[[AgentState], dict]:
    def lookup_tickets(state: AgentState) -> dict:
        query = TicketQuery.model_validate(state["route"].get("ticket_query") or {})
        result = deps.ticket_fn(query) if deps.ticket_fn else TicketsResult(outcome=ToolOutcome.UNAVAILABLE,
                                                                             error=_UNAVAILABLE["error"])
        entry = _tool_entry(SOURCE_TICKETS, result.outcome.value, result.model_dump(mode="json"))
        entry["query"] = query.model_dump(mode="json")
        return {"tool_results": [*state.get("tool_results", []), entry]}

    return lookup_tickets


def make_inventory_node(deps: AgentDependencies) -> Callable[[AgentState], dict]:
    def lookup_inventory(state: AgentState) -> dict:
        query = InventoryQuery.model_validate(state["route"].get("inventory_query") or {})
        result = deps.inventory_fn(query) if deps.inventory_fn else InventoryResult(outcome=ToolOutcome.UNAVAILABLE,
                                                                                    error=_UNAVAILABLE["error"])
        entry = _tool_entry(SOURCE_INVENTORY, result.outcome.value, result.model_dump(mode="json"))
        entry["query"] = query.model_dump(mode="json")
        return {"tool_results": [*state.get("tool_results", []), entry]}

    return lookup_inventory


_STATUS_LABELS = {"open": "abierto", "in_progress": "en progreso", "resolved": "resuelto", "discarded": "descartado"}
LIVE_SOURCE = {SOURCE_TICKETS: "gestor-de-incidentes (consulta en vivo)",
               SOURCE_INVENTORY: "gestor-de-inventario (consulta en vivo)"}


def tool_chunks(tool_results: list[dict]) -> list[dict]:
    """Convierte los resultados EXITOSOS de las tools en fragmentos de contexto con el mismo formato que los del RAG,
    para que `generate_answer()` los use igual (y cite su fuente). Los fallos no generan fragmentos."""
    chunks: list[dict] = []
    for entry in tool_results:
        if entry["outcome"] != ToolOutcome.OK.value:
            continue
        result = entry["result"]
        if entry["tool"] == SOURCE_TICKETS:
            tickets = result["tickets"]
            if not tickets:
                text = f"No hay tickets con esos filtros en el gestor de incidentes (consulta: {entry.get('query')})."
                chunks.append({"source_document": LIVE_SOURCE[SOURCE_TICKETS], "section": "Listado de tickets",
                               "chunk_index": 0, "text": text})
            for index, ticket in enumerate(tickets):
                text = (
                    f"Ticket #{ticket['id']}: {ticket['title']}. Estado: {_STATUS_LABELS.get(ticket['status'], ticket['status'])}. "
                    f"Categoría: {ticket['category']}. Origen: {ticket['origin']}. Sede: {ticket['branch']}. "
                    f"Creado: {ticket['created_at']}. Última actualización: {ticket['updated_at']}. "
                    f"Descripción: {ticket['description']}"
                )
                if len(tickets) < result["total"] and index == len(tickets) - 1:
                    text += f" (se muestran {len(tickets)} de {result['total']} tickets)"
                chunks.append({"source_document": LIVE_SOURCE[SOURCE_TICKETS], "section": f"Ticket {ticket['id']}",
                               "chunk_index": index, "text": text})
        elif entry["tool"] == SOURCE_INVENTORY:
            for index, product in enumerate(result["products"]):
                text = (f"Producto: {product['name']} (SKU {product['sku']}, {product['restaurant']}). "
                        f"Stock actual: {product['current_stock']:g}.")
                chunks.append({"source_document": LIVE_SOURCE[SOURCE_INVENTORY], "section": f"Producto {product['id']}",
                               "chunk_index": index, "text": text})
    return chunks


def failure_message(entry: dict) -> str:
    """Mensaje honesto y fijo para una tool que falló (nunca un estado inventado)."""
    outcome, query = entry["outcome"], entry.get("query") or {}
    not_found = outcome == ToolOutcome.NOT_FOUND.value
    if entry["tool"] == SOURCE_TICKETS:
        if query.get("ticket_id"):
            found_text, of_text = f"el ticket {query['ticket_id']}", f"del ticket {query['ticket_id']}"
        else:
            found_text, of_text = "los tickets", "de los tickets"
        if not_found:
            return f"No encuentro {found_text} en el gestor de incidentes; revisa que el número sea correcto."
        return (f"No pude confirmar el estado {of_text} ahora mismo: el gestor de incidentes no está disponible "
                "o no respondió a tiempo. Inténtalo de nuevo en unos minutos.")
    product = f" del producto «{query['product_name']}»" if query.get("product_name") else " del inventario"
    if not_found:
        found_text = f"el producto «{query['product_name']}»" if query.get("product_name") else "ese producto"
        return f"No encuentro {found_text} en el gestor de inventario; revisa el nombre."
    return (f"No pude confirmar el stock{product} ahora mismo: el gestor de inventario no está disponible "
            "o no respondió a tiempo. Inténtalo de nuevo en unos minutos.")


def failed_tools(state: AgentState) -> list[dict]:
    return [entry for entry in state.get("tool_results", []) if entry["outcome"] != ToolOutcome.OK.value]


def make_generate_node(deps: AgentDependencies) -> Callable[[AgentState], dict]:
    def generate_answer(state: AgentState) -> dict:
        context = [*state.get("context", []), *tool_chunks(state.get("tool_results", []))]
        answer = deps.generate_fn(state["question"], context)
        notices = [failure_message(entry) for entry in failed_tools(state)]  # una tool falló pero hay otra evidencia
        if notices:
            answer = "\n\n".join([answer, *notices])
        return {"answer": answer, "status": STATUS_ANSWERED}

    return generate_answer


def tool_fallback(state: AgentState) -> dict:
    answer = "\n".join(failure_message(entry) for entry in failed_tools(state))
    return {"answer": answer, "status": STATUS_TOOL_FALLBACK}


def no_information(state: AgentState) -> dict:
    return {"answer": NO_INFORMATION_ANSWER, "status": STATUS_NO_INFORMATION}


# --------------------------------------------------------------------------------------------------------------
# Aristas condicionales
# --------------------------------------------------------------------------------------------------------------
def route_after_receive(state: AgentState) -> str:
    """Pregunta vacía o demasiado larga -> error claro (sin consultar nada); si no, al enrutador."""
    return ROUTE_REJECT if state.get("status") == STATUS_INVALID_QUESTION else ROUTE_ROUTE


def has_evidence(state: AgentState) -> bool:
    """¿Hay algo real en lo que basar una respuesta? Fragmentos del RAG sobre el umbral o una tool que respondió."""
    return bool(state.get("context")) or any(
        entry["outcome"] == ToolOutcome.OK.value for entry in state.get("tool_results", [])
    )


def route_after_gathering(state: AgentState) -> str:
    """Fin de la recopilación. Con evidencia se genera; sin evidencia y con una tool fallida, respuesta honesta de
    fallback; sin evidencia ni fallo (el RAG no superó el umbral), 'no tengo información'. Nunca se genera en vacío."""
    if has_evidence(state):
        return ROUTE_GENERATE
    return ROUTE_TOOL_FALLBACK if failed_tools(state) else ROUTE_NO_INFORMATION


def next_source(state: AgentState, after: str | None) -> str:
    """Siguiente fuente planificada por el enrutador (en el orden tickets -> inventory -> rag) o, si ya no queda
    ninguna, el resultado de `route_after_gathering`."""
    planned = state.get("route", {}).get("sources", [SOURCE_RAG])
    order = [source for source in SOURCE_ORDER if source in planned]
    if after is not None:
        order = [source for source in order if SOURCE_ORDER.index(source) > SOURCE_ORDER.index(after)]
    return order[0] if order else route_after_gathering(state)


def route_after_route(state: AgentState) -> str:
    return next_source(state, None)


def route_after_tickets(state: AgentState) -> str:
    return next_source(state, SOURCE_TICKETS)


def route_after_inventory(state: AgentState) -> str:
    return next_source(state, SOURCE_INVENTORY)


def route_after_retrieve(state: AgentState) -> str:
    return next_source(state, SOURCE_RAG)
