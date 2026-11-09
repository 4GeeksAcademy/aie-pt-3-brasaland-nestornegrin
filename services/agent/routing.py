"""Enrutamiento: decide, a partir de la pregunta, si hace falta el RAG, una tool, o ambos (sin que el usuario lo indique).

Es una función pura y determinista (`plan_route`), a propósito: el enrutamiento queda explicado en el trace (`reason`),
es gratis, no depende de un modelo y se puede evaluar con casos fijos. El nodo `route_question` la llama a través de
`AgentDependencies.router_fn`, así que se puede sustituir por un clasificador con LLM sin tocar el grafo.

Criterio (la diferencia entre "conocimiento" y "datos operativos en vivo"):

* DATOS EN VIVO -> tool: el estado de un ticket concreto, listados de tickets por estado, stock de un producto.
  Cambian todo el tiempo, por eso no viven en el RAG.
* CONOCIMIENTO -> RAG: políticas, procedimientos, niveles de fidelización, alérgenos, mermas, proveedores...
* AMBOS: la pregunta mezcla las dos cosas (p. ej. "según el protocolo de merma, ¿cómo va el ticket 12?").
* Si no hay señal de datos en vivo, se va al RAG (que responde "no tengo información" si no hay nada relevante).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field

SOURCE_TICKETS = "tickets"
SOURCE_INVENTORY = "inventory"
SOURCE_RAG = "rag"
SOURCE_ORDER = (SOURCE_TICKETS, SOURCE_INVENTORY, SOURCE_RAG)  # orden de ejecución: primero datos en vivo, luego RAG

_TICKET_WORD = re.compile(r"\b(?:ticket|tickets|incidencia|incidencias|incidente|incidentes)\b")
_TICKET_ID = re.compile(
    r"(?:\b(?:ticket|incidencia|incidente)s?\s*(?:numero|num\.?|no\.?|n[oº°]\.?)?\s*#?\s*(\d+))|(?:#\s*(\d+))"
)
_LIVE_STATE_CUE = re.compile(
    r"\b(?:estado|abiert[oa]s?|resuelt[oa]s?|descartad[oa]s?|en progreso|en curso|en proceso|pendientes?|"
    r"cuantos?|cuantas?|listado|lista|ultim[oa]s?|recientes?)\b"
)
_STATUS_WORDS = (
    ("in_progress", re.compile(r"\b(?:en progreso|en curso|en proceso)\b")),
    ("resolved", re.compile(r"\bresuelt[oa]s?\b")),
    ("discarded", re.compile(r"\bdescartad[oa]s?\b")),
    ("open", re.compile(r"\b(?:abiert[oa]s?|pendientes?)\b")),
)
_INVENTORY_CUE = re.compile(r"\b(?:stock|existencias?|inventario)\b|\bcuant[oa]s?\s+(?:queda|quedan|tenemos)\b")
_PRODUCT_PATTERNS = (
    re.compile(r"\b(?:stock|existencias?|inventario|unidades|cantidad)\s+(?:actual\s+)?(?:de|del)\s+(?P<p>[^?.,;!]+)"),
    re.compile(r"\bcuant[oa]s?\s+(?:queda|quedan|tenemos)\s+(?:de|del)\s+(?P<p>[^?.,;!]+)"),
    re.compile(r"\bstock\s+(?P<p>[^?.,;!]+)"),
)
_KNOWLEDGE_CUE = re.compile(
    r"\b(?:protocolo|politica|politicas|procedimiento|norma|normas|regla|reglas|segun|programa de fidelidad|"
    r"nivel|niveles|descuento|alergenos?|gluten|merma|desperdicio|proveedor|proveedores|que debo hacer|que hago)\b"
)
_PRODUCT_STOPWORDS = {"el", "la", "los", "las", "un", "una", "unos", "unas", "ahora", "hoy", "actualmente", "mismo"}


@dataclass(frozen=True)
class RoutePlan:
    sources: tuple[str, ...]  # subconjunto ordenado de SOURCE_ORDER
    reason: str
    ticket_query: dict | None = None
    inventory_query: dict | None = None
    cues: dict = field(default_factory=dict)  # señales detectadas (para el trace)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["sources"] = list(self.sources)
        return data


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFD", text.lower())
    return "".join(char for char in folded if unicodedata.category(char) != "Mn")


def _extract_ticket_id(text: str) -> int | None:
    match = _TICKET_ID.search(text)
    if not match:
        return None
    value = int(match.group(1) or match.group(2))
    return value if value > 0 else None


def _extract_product(text: str) -> str | None:
    for pattern in _PRODUCT_PATTERNS:
        match = pattern.search(text)
        if match:
            words = [word for word in match.group("p").split() if word not in _PRODUCT_STOPWORDS]
            name = " ".join(words).strip()
            if name:
                return name[:100]
    return None


def plan_route(question: str) -> RoutePlan:
    text = _normalize(question)
    ticket_id = _extract_ticket_id(text)
    has_ticket_word = bool(_TICKET_WORD.search(text)) or ticket_id is not None
    live_cue = bool(_LIVE_STATE_CUE.search(text))
    wants_tickets = has_ticket_word and (ticket_id is not None or live_cue)
    wants_inventory = bool(_INVENTORY_CUE.search(text))
    wants_knowledge = bool(_KNOWLEDGE_CUE.search(text))
    cues = {"ticket_id": ticket_id, "ticket_word": has_ticket_word, "live_state": live_cue,
            "inventory": wants_inventory, "knowledge": wants_knowledge}

    ticket_query = inventory_query = None
    sources: list[str] = []
    if wants_tickets:
        sources.append(SOURCE_TICKETS)
        ticket_query = {"ticket_id": ticket_id}
        if ticket_id is None:
            status = next((value for value, pattern in _STATUS_WORDS if pattern.search(text)), None)
            ticket_query["status"] = status
    if wants_inventory:
        sources.append(SOURCE_INVENTORY)
        inventory_query = {"product_name": _extract_product(text)}
    if wants_knowledge or not sources:
        sources.append(SOURCE_RAG)

    if sources == [SOURCE_RAG]:
        reason = ("La pregunta es de conocimiento (políticas, procedimientos, menú...): se resuelve con el RAG."
                  if wants_knowledge else "Sin señales de datos en vivo: se consulta el RAG por defecto.")
    else:
        parts = []
        if SOURCE_TICKETS in sources:
            parts.append(f"pide el estado de tickets en vivo ({'ticket ' + str(ticket_id) if ticket_id else 'listado'})")
        if SOURCE_INVENTORY in sources:
            parts.append("pide stock en vivo")
        if SOURCE_RAG in sources:
            parts.append("también pide conocimiento estable (RAG)")
        reason = "La pregunta " + " y ".join(parts) + "."
    return RoutePlan(tuple(sources), reason, ticket_query, inventory_query, cues)
