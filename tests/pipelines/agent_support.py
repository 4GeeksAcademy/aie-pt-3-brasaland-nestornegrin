"""Dobles de prueba compartidos por los tests y los evals del agente (sin red, sin claves, sin modelos reales)."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from types import SimpleNamespace

from services.agent.nodes import AgentDependencies


def fake_embed(text: str, dim: int = 128) -> list[float]:
    """Embedding falso y determinista (bolsa de palabras con hash), el mismo criterio que usa `test_rag.py`."""
    normalized = unicodedata.normalize("NFD", text.lower())
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    vector = [0.0] * dim
    for token in re.findall(r"\w+", normalized):
        if len(token) >= 3:
            vector[int(hashlib.md5(token.encode()).hexdigest(), 16) % dim] += 1.0
    if not any(vector):
        vector[0] = 1.0
    return vector


def chunk(source: str, section: str, text: str, index: int = 0) -> dict:
    return {"company": "brasaland", "source_document": source, "section": section, "language": "es",
            "chunk_index": index, "text": text}


class SpyDependencies:
    """Dependencias del agente que registran cuántas veces se llamó a cada paso y con qué argumentos."""

    def __init__(self, context: list[dict] | None = None, answer: str = "Respuesta de prueba."):
        self.context = context if context is not None else [chunk("loyalty-program", "Niveles", "Oro: 50+ puntos.")]
        self.answer = answer
        self.retrieve_calls: list[str] = []
        self.generate_calls: list[tuple[str, list[dict]]] = []

    def retrieve(self, question: str) -> list[dict]:
        self.retrieve_calls.append(question)
        return list(self.context)

    def generate(self, question: str, context: list[dict]) -> str:
        self.generate_calls.append((question, context))
        return self.answer

    @property
    def deps(self) -> AgentDependencies:
        return AgentDependencies(retrieve_fn=self.retrieve, generate_fn=self.generate)


def extractive_generate(question: str, context: list[dict]) -> str:
    """Sustituto determinista del modelo de chat: responde con el texto de los fragmentos recuperados y su fuente.
    Sirve para comprobar que la respuesta del agente sale de la base de conocimiento y no de otro sitio."""
    if not context:
        raise AssertionError("generate_answer no debe ejecutarse sin contexto recuperado")
    body = "\n".join(item["text"] for item in context)
    sources = "\n".join(f"Fuente: {item['source_document']} — {item['section']}" for item in context)
    return f"{body}\n\n{sources}"


def stub_point(score: float, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(score=score, payload=payload)


# --------------------------------------------------------------------------------------------------------------
# Servidor MCP falso (SOLO para pruebas): responde a las mismas tools que `mcps/brasaland_mcp` (mismos nombres,
# argumentos y códigos de error) con datos en memoria y registra cada invocación. La implementación del agente nunca
# simula datos: pide las tools al servidor MCP; en las pruebas rápidas, ese servidor es este doble. El servidor MCP REAL
# (HTTP + OAuth) y el agente hablando con él se prueban en `tests/mcps/`.
# --------------------------------------------------------------------------------------------------------------
from services.agent.mcp_tools import McpCallError  # noqa: E402

TICKETS = [
    {"id": 482, "title": "Nevera de cocina sin enfriar", "description": "La nevera 2 no baja de 9 °C.",
     "category": "Fallo operativo", "origin": "branch", "branch": "Brasaland Laureles", "status": "in_progress",
     "created_at": "2026-11-01T10:00:00+00:00", "updated_at": "2026-11-03T15:30:00+00:00"},
    {"id": 12, "title": "Pedido de proveedor incompleto", "description": "Faltaron 3 cajas de pollo.",
     "category": "Solicitud", "origin": "internal", "branch": "central", "status": "open",
     "created_at": "2026-11-02T09:00:00+00:00", "updated_at": "2026-11-02T09:00:00+00:00"},
    {"id": 7, "title": "Queja por demora", "description": "Mesa 5 esperó 40 minutos.",
     "category": "Queja", "origin": "customer", "branch": "Brasaland Chapinero", "status": "resolved",
     "created_at": "2026-10-20T20:00:00+00:00", "updated_at": "2026-10-21T08:00:00+00:00"},
]
PRODUCTS = [
    {"id": 1, "name": "Pollo entero", "sku": "POL-001", "restaurant": "Brasaland Laureles", "current_stock": 42.0},
    {"id": 2, "name": "Carbón vegetal", "sku": "CAR-001", "restaurant": "Brasaland Laureles", "current_stock": 15.5},
]


class FakeGateway:
    """Sustituye a `McpGateway`: misma interfaz `call(tool, arguments)`, datos del `FakeBackend`."""

    def __init__(self, backend: "FakeBackend"):
        self.backend = backend

    def call(self, tool: str, arguments: dict):
        backend = self.backend
        backend.requests.append(("MCP", tool))
        if not backend.token_valid:
            raise McpCallError("MCP_UNAUTHORIZED", "token rechazado")
        if backend.mode == "timeout":
            raise McpCallError("BACKEND_TIMEOUT", "simulado")
        if backend.mode in ("down", "error"):
            raise McpCallError("BACKEND_UNAVAILABLE", "simulado")
        if tool == "incidents_get_ticket":
            found = next((t for t in backend.tickets if t["id"] == arguments["ticket_id"]), None)
            if found is None:
                raise McpCallError("NOT_FOUND", "Incidencia no encontrada")
            return found
        if tool == "incidents_list_tickets":
            rows = [t for t in backend.tickets if not arguments.get("status") or t["status"] == arguments["status"]]
            return {"total": len(rows), "tickets": rows[: arguments.get("limit", 10)]}
        if tool == "inventory_get_stock":
            rows = list(backend.products)
            if arguments.get("product_id") is not None:
                rows = [r for r in rows if r["id"] == arguments["product_id"]]
            if arguments.get("product_name"):
                needle = _fold(arguments["product_name"])
                rows = [r for r in rows if needle in _fold(r["name"])]
            if not rows and (arguments.get("product_id") is not None or arguments.get("product_name")):
                raise McpCallError("NOT_FOUND", "Producto no encontrado")
            return {"total": len(rows), "products": rows[: arguments.get("limit", 10)]}
        raise McpCallError("MCP_TOOL_NOT_FOUND", tool)


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn").strip()


class FakeBackend:
    """Doble del servidor MCP con modos de fallo: `mode` = "ok" | "timeout" | "down" | "error"."""

    def __init__(self, mode: str = "ok", tickets=None, products=None, token_valid: bool = True):
        self.mode = mode
        self.tickets = TICKETS if tickets is None else tickets
        self.products = PRODUCTS if products is None else products
        self.token_valid = token_valid
        self.requests: list[tuple[str, str]] = []  # ("MCP", nombre de la tool) por cada invocación

    def client(self) -> FakeGateway:
        return FakeGateway(self)

    def dependencies(self, rag: "SpyDependencies | None" = None) -> AgentDependencies:
        from services.agent.mcp_tools import McpInventoryTool, McpTicketTool

        rag = rag or SpyDependencies()
        gateway = self.client()
        return AgentDependencies(retrieve_fn=rag.retrieve, generate_fn=rag.generate,
                                 ticket_fn=McpTicketTool(gateway), inventory_fn=McpInventoryTool(gateway))
