"""Clientes HTTP del backend propio (`services/api`): el gestor de incidentes y el de inventario REALES.

No hay datos simulados ni un dataset paralelo: cada tool llama a un endpoint existente.

* `InventoryBackend` (y la base `ReadOnlyBackend`) solo tienen `get()`. No existe ningún método para escribir en el inventario: la solo-lectura está
  en la estructura del cliente, además de en la guardia del servidor (`middleware.py`) y en los scopes (no hay scope de
  escritura de inventario).
* `IncidentsBackend` añade exactamente dos escrituras, ambas con su endpoint dedicado: crear (`POST /api/incidents`) y
  cambiar de estado (`PATCH /api/incidents/{id}/status`, el endpoint de ciclo de vida; nunca un PATCH genérico).
* Autenticación: la API exige JWT, así que el servidor MCP hace login con una cuenta de servicio (`MCP_BACKEND_EMAIL` /
  `MCP_BACKEND_PASSWORD`) y reutiliza el token (lo renueva una vez si recibe 401). Es una credencial DISTINTA del token
  OAuth del cliente MCP: el cliente se autentica contra el proveedor OAuth, el servidor contra el backend.
* Timeout explícito y numérico en cada llamada.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from . import errors
from .config import TOOL_TIMEOUT_SECONDS
from .errors import McpToolError

logger = logging.getLogger(__name__)


class ReadOnlyBackend:
    """Cliente autenticado de SOLO LECTURA (`get`). Base de los dos clientes de abajo."""

    def __init__(
        self,
        base_url: str,
        email: str,
        password: str,
        timeout: float = TOOL_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.timeout = float(timeout)
        self._email, self._password = email, password
        self._http = httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(self.timeout), transport=transport)
        self._token: str | None = None
        self._lock = asyncio.Lock()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._send("GET", path, params=params)

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- internos ---------------------------------------------------------------------------------------------
    async def _send(self, method: str, path: str, *, params=None, json=None) -> Any:
        try:
            response = await self._request(method, path, params, json)
            if response.status_code == 401:  # token caducado: se renueva una sola vez
                self._token = None
                response = await self._request(method, path, params, json)
            response.raise_for_status()
            return response.json()
        except McpToolError:
            raise
        except Exception as error:  # noqa: BLE001 - se traduce a un código estable, sin filtrar detalles internos
            raise translate_backend_error(error, method, path) from error

    async def _request(self, method: str, path: str, params, json) -> httpx.Response:
        token = await self._authenticate()
        return await self._http.request(method, path, params=params, json=json,
                                        headers={"Authorization": f"Bearer {token}"})

    async def _authenticate(self) -> str:
        async with self._lock:
            if self._token:
                return self._token
            if not self._email or not self._password:
                raise McpToolError(errors.BACKEND_UNAUTHORIZED,
                                   "El servidor MCP no tiene credenciales para el backend (MCP_BACKEND_EMAIL/PASSWORD).")
            response = await self._http.post("/auth/login", json={"email": self._email, "password": self._password})
            response.raise_for_status()
            self._token = response.json()["access_token"]
            return self._token


class InventoryBackend(ReadOnlyBackend):
    """Gestor de inventario: solo hereda `get()`. No se le puede añadir una escritura sin tocar este archivo."""


class IncidentsBackend(ReadOnlyBackend):
    """Lectura + las dos escrituras permitidas del gestor de incidentes. Sin `put`/`delete`/PATCH genérico."""

    async def create_ticket(self, payload: dict[str, Any]) -> Any:
        return await self._send("POST", "/api/incidents", json=payload)

    async def update_ticket_status(self, ticket_id: int, status: str) -> Any:
        return await self._send("PATCH", f"/api/incidents/{int(ticket_id)}/status", json={"status": status})


def _detail_text(response: Any) -> str:
    try:
        detail = response.json().get("detail")
    except Exception:  # noqa: BLE001
        return ""
    if isinstance(detail, list):  # errores de validación de la API: [{loc, msg, type}]
        return "; ".join(f"{'.'.join(str(p) for p in item.get('loc', []) if p != 'body')}: {item.get('msg')}"
                         for item in detail if isinstance(item, dict))
    return str(detail or "")


def translate_backend_error(error: Exception, method: str, path: str) -> McpToolError:
    """Traduce un fallo HTTP del backend a un `McpToolError` con código estable (sin URLs ni stack traces)."""
    if isinstance(error, httpx.TimeoutException):
        return McpToolError(errors.BACKEND_TIMEOUT, "El gestor no respondió dentro del tiempo límite.")
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        detail = _detail_text(response)
        if status == 404:
            return McpToolError(errors.NOT_FOUND, detail or "El recurso no existe.")
        if status in (401, 403):
            return McpToolError(errors.BACKEND_UNAUTHORIZED, "El backend rechazó las credenciales del servidor MCP.")
        if status in (400, 422):
            code = errors.INVALID_TRANSITION if method == "PATCH" else errors.VALIDATION_ERROR
            return McpToolError(code, detail or "El backend rechazó la petición.")
        return McpToolError(errors.BACKEND_UNAVAILABLE, f"El backend respondió con un error ({status}).")
    if isinstance(error, httpx.TransportError):
        return McpToolError(errors.BACKEND_UNAVAILABLE, "No se pudo conectar con el backend.")
    logger.exception("Respuesta inesperada del backend (%s %s)", method, path)
    return McpToolError(errors.BACKEND_UNAVAILABLE, "El backend devolvió una respuesta inesperada.")
