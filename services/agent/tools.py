"""Tools de solo lectura del agente: consultan los servicios REALES del monorepo (nunca datos simulados).

    TicketTool     -> gestor de incidentes   GET /api/incidents  y  GET /api/incidents/{id}
    InventoryTool  -> gestor de inventario   GET /inventory/products

Reglas que cumplen las dos (y que comprueban los tests):

* Contrato tipado de entrada y salida (pydantic): `TicketQuery` -> `TicketsResult`, `InventoryQuery` -> `InventoryResult`.
* Solo lectura: `BackendClient` solo expone `get()`; no existe ningún método para crear, modificar o borrar. Lo único que
  no es un GET es el login (`POST /auth/login`), necesario para obtener el JWT que exigen estos servicios.
* Transporte HTTP con autenticación: las credenciales vienen del entorno (`AGENT_API_EMAIL`, `AGENT_API_PASSWORD`),
  nunca del código; el JWT se pide una vez y se renueva si el servicio responde 401.
* Timeout explícito y numérico: `TOOL_TIMEOUT_SECONDS` (4 s) en cada llamada HTTP, para que un servicio que no responde
  no deje colgado el grafo.
* Nunca lanzan: cualquier fallo (timeout, servicio caído, 404, sin credenciales...) vuelve como un resultado con
  `outcome` distinto de `ok`; el grafo lo convierte en una respuesta honesta (ruta de fallback), no en un error.
* Una sola responsabilidad: una tool para tickets y otra para inventario. No hay una tool que combine las dos.
"""
from __future__ import annotations

import logging
import os
import threading
import unicodedata
from enum import Enum
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

TOOL_TIMEOUT_SECONDS = 4.0  # segundos, por operación HTTP (conexión, lectura...) de cada llamada
DEFAULT_BASE_URL = "http://localhost:8000"
MAX_ITEMS = 10  # tope de filas que una tool devuelve al agente


class ToolOutcome(str, Enum):
    OK = "ok"
    NOT_FOUND = "not_found"  # el recurso no existe (ticket o producto)
    TIMEOUT = "timeout"  # el servicio no respondió dentro de TOOL_TIMEOUT_SECONDS
    UNAVAILABLE = "unavailable"  # servicio caído, error 5xx o respuesta inesperada
    UNAUTHORIZED = "unauthorized"  # faltan credenciales o el servicio las rechazó
    INVALID = "invalid"  # el servicio rechazó la consulta (400/422)


# --------------------------------------------------------------------------------------------------------------
# Contratos
# --------------------------------------------------------------------------------------------------------------
TicketStatus = Literal["open", "in_progress", "resolved", "discarded"]


class TicketQuery(BaseModel):
    """Entrada de la tool de tickets: un ticket concreto (`ticket_id`) o un listado filtrado por estado."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: int | None = Field(default=None, gt=0)
    status: TicketStatus | None = None
    limit: int = Field(default=5, ge=1, le=MAX_ITEMS)


class TicketInfo(BaseModel):
    """Los mismos campos que expone `GET /api/incidents`."""

    model_config = ConfigDict(extra="ignore")

    id: int
    title: str
    description: str
    category: str
    origin: str
    branch: str
    status: str
    created_at: str
    updated_at: str


class TicketsResult(BaseModel):
    outcome: ToolOutcome
    tickets: list[TicketInfo] = Field(default_factory=list)
    total: int = 0  # coincidencias totales (la lista se recorta a `limit`)
    error: str | None = None


class InventoryQuery(BaseModel):
    """Entrada de la tool de inventario: un producto por `product_id` o por nombre (o todos si no se indica)."""

    model_config = ConfigDict(extra="forbid")

    product_id: int | None = Field(default=None, gt=0)
    product_name: str | None = Field(default=None, min_length=1, max_length=100)
    limit: int = Field(default=MAX_ITEMS, ge=1, le=MAX_ITEMS)


class ProductStock(BaseModel):
    """Los mismos campos que expone `GET /inventory/products`."""

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    sku: str
    restaurant: str
    current_stock: float


class InventoryResult(BaseModel):
    outcome: ToolOutcome
    products: list[ProductStock] = Field(default_factory=list)
    total: int = 0
    error: str | None = None


# --------------------------------------------------------------------------------------------------------------
# Cliente HTTP de solo lectura
# --------------------------------------------------------------------------------------------------------------
class MissingCredentialsError(RuntimeError):
    """No hay credenciales para autenticarse contra el backend (AGENT_API_EMAIL / AGENT_API_PASSWORD)."""


class BackendClient:
    """Cliente HTTP del backend propio (`services/api`). SOLO expone `get()`: una tool no puede escribir."""

    def __init__(
        self,
        base_url: str | None = None,
        email: str | None = None,
        password: str | None = None,
        timeout: float = TOOL_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
        http_client: httpx.Client | None = None,
    ):
        self.base_url = (base_url or os.environ.get("AGENT_API_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = float(timeout)
        self._email = email
        self._password = password
        # `http_client` solo lo usan las pruebas (p. ej. un TestClient de FastAPI contra el servicio real).
        self._http = http_client or httpx.Client(
            base_url=self.base_url, timeout=httpx.Timeout(self.timeout), transport=transport
        )
        self._token: str | None = None
        self._lock = threading.Lock()

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET autenticado que devuelve el JSON. Si el servicio responde 401 se renueva el token UNA vez."""
        response = self._get_once(path, params)
        if response.status_code == 401:
            self._token = None
            response = self._get_once(path, params)
        response.raise_for_status()
        return response.json()

    def _get_once(self, path: str, params: dict[str, Any] | None) -> httpx.Response:
        return self._http.get(path, params=params, headers={"Authorization": f"Bearer {self._authenticate()}"})

    def _authenticate(self) -> str:
        with self._lock:
            if self._token:
                return self._token
            email = self._email or os.environ.get("AGENT_API_EMAIL")
            password = self._password or os.environ.get("AGENT_API_PASSWORD")
            if not email or not password:
                raise MissingCredentialsError("Faltan AGENT_API_EMAIL / AGENT_API_PASSWORD para consultar el backend.")
            response = self._http.post("/auth/login", json={"email": email, "password": password})
            response.raise_for_status()
            self._token = response.json()["access_token"]
            return self._token


def classify_failure(error: Exception, service: str) -> tuple[ToolOutcome, str]:
    """Traduce una excepción a (outcome, mensaje seguro). El mensaje nunca incluye URLs, tokens ni stack traces."""
    if isinstance(error, httpx.TimeoutException):
        return ToolOutcome.TIMEOUT, f"El {service} no respondió en {TOOL_TIMEOUT_SECONDS:g} s."
    if isinstance(error, MissingCredentialsError):
        return ToolOutcome.UNAUTHORIZED, f"El agente no tiene credenciales para consultar el {service}."
    status = getattr(getattr(error, "response", None), "status_code", None)  # HTTPStatusError (de httpx o de un fork)
    if isinstance(status, int):
        if status == 404:
            return ToolOutcome.NOT_FOUND, "El recurso no existe."
        if status in (401, 403):
            return ToolOutcome.UNAUTHORIZED, f"El {service} rechazó las credenciales del agente."
        if status in (400, 422):
            return ToolOutcome.INVALID, f"El {service} rechazó la consulta."
        return ToolOutcome.UNAVAILABLE, f"El {service} respondió con un error ({status})."
    if isinstance(error, httpx.TransportError):
        return ToolOutcome.UNAVAILABLE, f"No se pudo conectar con el {service}."
    logger.exception("Fallo inesperado en una tool del agente")
    return ToolOutcome.UNAVAILABLE, f"El {service} devolvió una respuesta inesperada."


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFD", text.lower())
    return "".join(char for char in folded if unicodedata.category(char) != "Mn").strip()


# --------------------------------------------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------------------------------------------
class TicketTool:
    """Consulta de tickets de soporte en el gestor de incidentes (solo lectura)."""

    name = "tickets"
    service = "gestor de incidentes"

    def __init__(self, client: BackendClient | None = None):
        self._client = client

    @property
    def client(self) -> BackendClient:
        if self._client is None:
            self._client = BackendClient()
        return self._client

    def __call__(self, query: TicketQuery) -> TicketsResult:
        try:
            if query.ticket_id is not None:
                tickets = [TicketInfo.model_validate(self.client.get(f"/api/incidents/{query.ticket_id}"))]
                return TicketsResult(outcome=ToolOutcome.OK, tickets=tickets, total=1)
            params = {"status": query.status} if query.status else None
            rows = [TicketInfo.model_validate(row) for row in self.client.get("/api/incidents", params)]
            return TicketsResult(outcome=ToolOutcome.OK, tickets=rows[: query.limit], total=len(rows))
        except Exception as error:  # noqa: BLE001 - una tool nunca lanza: devuelve el motivo
            outcome, message = classify_failure(error, self.service)
            return TicketsResult(outcome=outcome, error=message)


class InventoryTool:
    """Consulta de stock por producto en el gestor de inventario (solo lectura)."""

    name = "inventory"
    service = "gestor de inventario"

    def __init__(self, client: BackendClient | None = None):
        self._client = client

    @property
    def client(self) -> BackendClient:
        if self._client is None:
            self._client = BackendClient()
        return self._client

    def __call__(self, query: InventoryQuery) -> InventoryResult:
        try:
            rows = [ProductStock.model_validate(row) for row in self.client.get("/inventory/products")]
            if query.product_id is not None:
                rows = [row for row in rows if row.id == query.product_id]
            if query.product_name:
                needle = _normalize(query.product_name)
                rows = [row for row in rows if needle in _normalize(row.name)]
            if not rows and (query.product_id is not None or query.product_name):
                return InventoryResult(outcome=ToolOutcome.NOT_FOUND, error="No hay ningún producto con ese nombre.")
            return InventoryResult(outcome=ToolOutcome.OK, products=rows[: query.limit], total=len(rows))
        except Exception as error:  # noqa: BLE001
            outcome, message = classify_failure(error, self.service)
            return InventoryResult(outcome=outcome, error=message)
