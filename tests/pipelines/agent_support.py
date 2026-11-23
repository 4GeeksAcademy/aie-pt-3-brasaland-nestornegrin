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
# Backend HTTP falso (SOLO para pruebas): sirve los mismos contratos que el gestor de incidentes y de inventario reales
# (`GET /api/incidents[/{id}]`, `GET /inventory/products`, `POST /auth/login`) y registra cada petición. La
# implementación del agente nunca simula datos: lee del backend por HTTP; en las pruebas, ese backend es este.
# El contrato contra el backend REAL se verifica en `services/api/tests/test_agent_tools_integration.py`.
# --------------------------------------------------------------------------------------------------------------
import httpx  # noqa: E402

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


class FakeBackend:
    """Backend HTTP falso con modos de fallo: `mode` = "ok" | "timeout" | "down" | "error"."""

    def __init__(self, mode: str = "ok", tickets=None, products=None, token_valid: bool = True):
        self.mode = mode
        self.tickets = TICKETS if tickets is None else tickets
        self.products = PRODUCTS if products is None else products
        self.token_valid = token_valid
        self.requests: list[tuple[str, str]] = []  # (método, ruta)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if self.mode == "timeout":
            raise httpx.ReadTimeout("simulado", request=request)
        if self.mode == "down":
            raise httpx.ConnectError("simulado", request=request)
        if request.url.path == "/auth/login":
            return httpx.Response(200 if self.token_valid else 401, json={"access_token": "jwt-de-prueba"})
        if request.headers.get("authorization") != "Bearer jwt-de-prueba":
            return httpx.Response(401, json={"detail": "Credenciales inválidas"})
        if self.mode == "error":
            return httpx.Response(500, json={"detail": "boom"})
        path = request.url.path
        if path == "/api/incidents":
            status = request.url.params.get("status")
            return httpx.Response(200, json=[t for t in self.tickets if not status or t["status"] == status])
        if path.startswith("/api/incidents/"):
            found = next((t for t in self.tickets if str(t["id"]) == path.rsplit("/", 1)[1]), None)
            return httpx.Response(200, json=found) if found else httpx.Response(404, json={"detail": "no existe"})
        if path == "/inventory/products":
            return httpx.Response(200, json=self.products)
        return httpx.Response(404)

    def client(self, **kwargs):
        from services.agent.tools import BackendClient

        kwargs.setdefault("email", "agente@brasaland.test")
        kwargs.setdefault("password", "clave-de-prueba")
        return BackendClient(base_url="http://backend.test", transport=httpx.MockTransport(self.handler), **kwargs)

    def dependencies(self, rag: "SpyDependencies | None" = None) -> AgentDependencies:
        from services.agent.tools import InventoryTool, TicketTool

        rag = rag or SpyDependencies()
        client = self.client()
        return AgentDependencies(retrieve_fn=rag.retrieve, generate_fn=rag.generate,
                                 ticket_fn=TicketTool(client), inventory_fn=InventoryTool(client))
