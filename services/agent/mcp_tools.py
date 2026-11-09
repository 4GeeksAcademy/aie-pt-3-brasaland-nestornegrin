"""Tools del agente que consumen el servidor MCP de Brasaland (`mcps/brasaland_mcp`) con `langchain-mcp-adapters`.

Sustituyen a las tools directas (`TicketTool`/`InventoryTool`/`BackendClient`, eliminadas de `tools.py`): el agente YA NO
habla con el gestor de incidentes ni con el de inventario; solo habla MCP. Un único camino:

    nodo del grafo -> McpTicketTool / McpInventoryTool -> McpGateway -> MCP (HTTP + Bearer OAuth) -> backend

* `McpGateway` es el único punto con red: obtiene un token OAuth 2.1 (client credentials) del proveedor, abre una
  conexión Streamable HTTP con `MultiServerMCPClient` y ejecuta UNA tool descubierta en el servidor.
* Las tools conservan el contrato tipado de `tools.py` (`TicketQuery -> TicketsResult`, ...), así que el grafo, el
  enrutamiento, el fallback y los traces no cambian.
* Nunca lanzan: los códigos de error del servidor (`[NOT_FOUND] ...`, `[FORBIDDEN_SCOPE] ...`) se traducen a `ToolOutcome`.
* El agente solo pide scopes de LECTURA (`tickets:read inventory:read`): mínimo privilegio también en el cliente.

Variables de entorno: `MCP_SERVER_URL`, `AGENT_MCP_TOKEN_URL`, `AGENT_MCP_CLIENT_ID`, `AGENT_MCP_CLIENT_SECRET`,
`AGENT_MCP_AUDIENCE` (por defecto, `MCP_SERVER_URL`), `AGENT_MCP_SCOPES`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Awaitable, Callable, TypeVar

import httpx

from .tools import (
    InventoryQuery,
    InventoryResult,
    ProductStock,
    TicketInfo,
    TicketQuery,
    TicketsResult,
    ToolOutcome,
)

logger = logging.getLogger(__name__)

CALL_TIMEOUT_SECONDS = 8.0  # tope de una invocación completa (token + conexión + tool)
DEFAULT_SCOPES = "tickets:read inventory:read"
_ERROR_PREFIX = re.compile(r"^\[(?P<code>[A-Z_]+)\]\s*(?P<message>.*)$", re.DOTALL)
T = TypeVar("T")


class McpCallError(Exception):
    """Fallo de una invocación MCP: `code` es el del servidor ([NOT_FOUND]...) o uno local (MCP_UNAVAILABLE...)."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(f"[{code}] {message}")
        self.code, self.message = code, message


class McpConfigError(McpCallError):
    def __init__(self, message: str):
        super().__init__("MCP_NOT_CONFIGURED", message)


# Código de error del servidor -> resultado que entiende el grafo.
OUTCOME_BY_CODE: dict[str, ToolOutcome] = {
    "NOT_FOUND": ToolOutcome.NOT_FOUND,
    "BACKEND_TIMEOUT": ToolOutcome.TIMEOUT,
    "MCP_TIMEOUT": ToolOutcome.TIMEOUT,
    "FORBIDDEN_SCOPE": ToolOutcome.UNAUTHORIZED,
    "BACKEND_UNAUTHORIZED": ToolOutcome.UNAUTHORIZED,
    "MCP_UNAUTHORIZED": ToolOutcome.UNAUTHORIZED,
    "MCP_NOT_CONFIGURED": ToolOutcome.UNAUTHORIZED,
    "VALIDATION_ERROR": ToolOutcome.INVALID,
    "INVALID_TRANSITION": ToolOutcome.INVALID,
    "READ_ONLY_VIOLATION": ToolOutcome.INVALID,
}
SERVICE_BY_TOOL = {"tickets": "gestor de incidentes", "inventory": "gestor de inventario"}


def _run_sync(coro_factory: Callable[[], Awaitable[T]]) -> T:
    """Ejecuta una corrutina desde código síncrono (los nodos del grafo son síncronos), con o sin bucle activo."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())  # type: ignore[arg-type]
    with ThreadPoolExecutor(max_workers=1) as pool:  # ya hay un bucle en este hilo: se usa otro
        return pool.submit(lambda: asyncio.run(coro_factory())).result()  # type: ignore[arg-type]


class TokenProvider:
    """Token OAuth 2.1 por client credentials contra el proveedor (Auth0); se cachea hasta poco antes de caducar."""

    def __init__(self, token_url: str | None = None, client_id: str | None = None, client_secret: str | None = None,
                 audience: str | None = None, scopes: str | None = None, http: httpx.Client | None = None):
        self.token_url = token_url or os.environ.get("AGENT_MCP_TOKEN_URL")
        self.client_id = client_id or os.environ.get("AGENT_MCP_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("AGENT_MCP_CLIENT_SECRET")
        self.audience = audience or os.environ.get("AGENT_MCP_AUDIENCE") or os.environ.get("MCP_SERVER_URL")
        self.scopes = scopes or os.environ.get("AGENT_MCP_SCOPES") or DEFAULT_SCOPES
        self._http = http or httpx.Client(timeout=httpx.Timeout(CALL_TIMEOUT_SECONDS / 2))
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()

    def get(self) -> str:
        with self._lock:
            if self._token and self._token[1] > time.monotonic() + 30:
                return self._token[0]
            if not (self.token_url and self.client_id and self.client_secret):
                raise McpConfigError("Faltan AGENT_MCP_TOKEN_URL / AGENT_MCP_CLIENT_ID / AGENT_MCP_CLIENT_SECRET.")
            try:
                response = self._http.post(self.token_url, data={
                    "grant_type": "client_credentials", "client_id": self.client_id,
                    "client_secret": self.client_secret, "audience": self.audience, "scope": self.scopes})
            except httpx.TimeoutException as error:
                raise McpCallError("MCP_TIMEOUT", "El proveedor OAuth no respondió.") from error
            except httpx.HTTPError as error:
                raise McpCallError("MCP_UNAVAILABLE", "No se pudo contactar con el proveedor OAuth.") from error
            if response.status_code in (400, 401, 403):
                raise McpCallError("MCP_UNAUTHORIZED", "El proveedor OAuth rechazó las credenciales del agente.")
            response.raise_for_status()
            body = response.json()
            self._token = (body["access_token"], time.monotonic() + float(body.get("expires_in", 300)))
            return self._token[0]

    def invalidate(self) -> None:
        with self._lock:
            self._token = None


class McpGateway:
    """Único punto de red del agente: descubre las tools del servidor MCP y ejecuta una con el token OAuth vigente."""

    def __init__(self, server_url: str | None = None, token_provider: TokenProvider | None = None,
                 timeout: float = CALL_TIMEOUT_SECONDS):
        self.server_url = server_url or os.environ.get("MCP_SERVER_URL")
        self.tokens = token_provider or TokenProvider()
        self.timeout = timeout

    def call(self, tool: str, arguments: dict[str, Any]) -> Any:
        """Ejecuta `tool` y devuelve su JSON. Lanza `McpCallError` (con el código del servidor) si falla."""
        if not self.server_url:
            raise McpConfigError("Falta MCP_SERVER_URL: el agente no sabe dónde está el servidor MCP.")
        try:
            return _run_sync(lambda: asyncio.wait_for(self._call(tool, arguments), self.timeout))
        except McpCallError:
            raise
        except (asyncio.TimeoutError, TimeoutError) as error:
            raise McpCallError("MCP_TIMEOUT", "El servidor MCP no respondió a tiempo.") from error
        except BaseException as error:  # noqa: BLE001 - ExceptionGroup de anyio incluido
            raise self._translate(error) from error

    async def _call(self, tool: str, arguments: dict[str, Any]) -> Any:
        from langchain_mcp_adapters.client import MultiServerMCPClient  # import diferido: solo si hay MCP

        client = MultiServerMCPClient({"brasaland": {
            "transport": "streamable_http", "url": self.server_url,
            "headers": {"Authorization": f"Bearer {self.tokens.get()}"}}})
        tools = {item.name: item for item in await client.get_tools()}  # discovery contra el servidor real
        if tool not in tools:
            raise McpCallError("MCP_TOOL_NOT_FOUND", f"El servidor MCP no expone la tool '{tool}'.")
        return self._parse(await tools[tool].ainvoke(arguments))

    @staticmethod
    def _parse(content: Any) -> Any:
        if isinstance(content, list):
            content = " ".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
        text = str(content).strip()
        match = _ERROR_PREFIX.match(text)
        if match:
            raise McpCallError(match["code"], match["message"].strip())
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise McpCallError("MCP_BAD_RESPONSE", "El servidor MCP devolvió una respuesta no JSON.") from error

    def _translate(self, error: BaseException) -> McpCallError:
        leaves = list(getattr(error, "exceptions", None) or [error])
        for leaf in leaves:
            status = getattr(getattr(leaf, "response", None), "status_code", None)
            if status in (401, 403):
                self.tokens.invalidate()
                return McpCallError("MCP_UNAUTHORIZED", "El servidor MCP rechazó el token del agente.")
            if isinstance(leaf, httpx.TimeoutException):
                return McpCallError("MCP_TIMEOUT", "El servidor MCP no respondió a tiempo.")
        logger.warning("Fallo de transporte MCP: %s", type(leaves[0]).__name__)
        return McpCallError("MCP_UNAVAILABLE", "No se pudo conectar con el servidor MCP.")


def failure(code: str, tool_name: str) -> tuple[ToolOutcome, str]:
    """(outcome, mensaje seguro) para un código de error: nunca incluye URLs, tokens ni trazas."""
    service = SERVICE_BY_TOOL[tool_name]
    outcome = OUTCOME_BY_CODE.get(code, ToolOutcome.UNAVAILABLE)
    messages = {
        ToolOutcome.NOT_FOUND: "El recurso no existe.",
        ToolOutcome.TIMEOUT: f"El {service} no respondió a tiempo.",
        ToolOutcome.UNAUTHORIZED: f"El agente no tiene autorización para consultar el {service}.",
        ToolOutcome.INVALID: f"El {service} rechazó la consulta.",
        ToolOutcome.UNAVAILABLE: f"No se pudo consultar el {service}.",
    }
    return outcome, messages[outcome]


class McpTicketTool:
    """Consulta de tickets vía MCP (`incidents_get_ticket` / `incidents_list_tickets`)."""

    name = "tickets"

    def __init__(self, gateway: McpGateway | None = None):
        self.gateway = gateway or McpGateway()

    def __call__(self, query: TicketQuery) -> TicketsResult:
        try:
            if query.ticket_id is not None:
                data = self.gateway.call("incidents_get_ticket", {"ticket_id": query.ticket_id})
                return TicketsResult(outcome=ToolOutcome.OK, tickets=[TicketInfo.model_validate(data)], total=1)
            arguments: dict[str, Any] = {"limit": query.limit}
            if query.status:
                arguments["status"] = query.status
            data = self.gateway.call("incidents_list_tickets", arguments)
            return TicketsResult(outcome=ToolOutcome.OK, total=int(data["total"]),
                                 tickets=[TicketInfo.model_validate(row) for row in data["tickets"]])
        except McpCallError as error:
            outcome, message = failure(error.code, self.name)
            return TicketsResult(outcome=outcome, error=message)
        except Exception:  # noqa: BLE001 - una tool nunca lanza
            logger.exception("Respuesta MCP inesperada (tickets)")
            return TicketsResult(outcome=ToolOutcome.UNAVAILABLE, error="El gestor de incidentes devolvió una respuesta inesperada.")


class McpInventoryTool:
    """Consulta de stock vía MCP (`inventory_get_stock`, de solo lectura)."""

    name = "inventory"

    def __init__(self, gateway: McpGateway | None = None):
        self.gateway = gateway or McpGateway()

    def __call__(self, query: InventoryQuery) -> InventoryResult:
        try:
            arguments: dict[str, Any] = {"limit": query.limit}
            if query.product_id is not None:
                arguments["product_id"] = query.product_id
            if query.product_name:
                arguments["product_name"] = query.product_name
            data = self.gateway.call("inventory_get_stock", arguments)
            return InventoryResult(outcome=ToolOutcome.OK, total=int(data["total"]),
                                   products=[ProductStock.model_validate(row) for row in data["products"]])
        except McpCallError as error:
            outcome, message = failure(error.code, self.name)
            return InventoryResult(outcome=outcome, error=message)
        except Exception:  # noqa: BLE001
            logger.exception("Respuesta MCP inesperada (inventario)")
            return InventoryResult(outcome=ToolOutcome.UNAVAILABLE, error="El gestor de inventario devolvió una respuesta inesperada.")
