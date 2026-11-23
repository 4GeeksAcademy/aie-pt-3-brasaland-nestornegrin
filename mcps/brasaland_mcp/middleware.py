"""Middleware del servidor MCP: autorización por scope de cada tool, guardia de solo lectura del inventario, normalización
de errores y un registro de auditoría por CADA invocación de tool (también las rechazadas).

Orden dentro de `on_call_tool`:
  1. identificar al cliente (claims del token que ya validó MCP Auth);
  2. si la tool no existe y su nombre es una escritura sobre inventario -> READ_ONLY_VIOLATION (rechazo explícito);
  3. comprobar el scope que exige la tool -> FORBIDDEN_SCOPE;
  4. comprobar los argumentos: un campo desconocido nunca se ignora (READ_ONLY_VIOLATION si es una escritura sobre
     inventario, VALIDATION_ERROR en el resto);
  5. ejecutar la tool y traducir cualquier fallo a un código estable;
  6. escribir el registro de auditoría (tool, cliente, resultado, duración).
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastmcp.exceptions import ToolError
from fastmcp.exceptions import ValidationError as FastMCPValidationError
from fastmcp.server.middleware import Middleware

from . import errors
from .errors import McpToolError
from .tools import INVENTORY_TOOLS, TOOL_ARGUMENTS, TOOL_SCOPES

audit_logger = logging.getLogger("brasaland.mcp.audit")
logger = logging.getLogger(__name__)

# Verbos y campos que delatan un intento de MODIFICAR (no consultar) el inventario.
_WRITE_VERBS = r"(?:create|add|insert|update|set|adjust|modify|edit|write|delete|remove|drop|decrement|increment|restock|consume|patch|put|post)"
_WRITE_TOOL_NAME = re.compile(rf"(?:inventory|stock|product|ingredient).*{_WRITE_VERBS}|{_WRITE_VERBS}.*(?:inventory|stock|product|ingredient)",
                              re.IGNORECASE)
_WRITE_ARGUMENTS = frozenset({
    "quantity", "stock", "current_stock", "new_stock", "set_stock", "delta", "adjustment", "amount", "increment",
    "decrement", "operation", "action", "mode", "write", "delete", "reason", "supplier", "sku", "name", "restaurant"})

Identity = Callable[[], Any]  # devuelve el AuthInfo del token validado (o None)


def configure_audit_log(path: Path) -> None:
    """Un registro JSON por línea en `path` (además de la salida estándar del logger)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not any(getattr(h, "baseFilename", None) == str(path.resolve()) for h in audit_logger.handlers):
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        audit_logger.addHandler(handler)
    audit_logger.setLevel(logging.INFO)


def is_inventory_write_attempt(tool_name: str) -> bool:
    return tool_name not in TOOL_SCOPES and bool(_WRITE_TOOL_NAME.search(tool_name))


class AuditGuardMiddleware(Middleware):
    def __init__(self, identity: Identity):
        self._identity = identity

    async def on_call_tool(self, context, call_next):
        started = time.perf_counter()
        name = context.message.name
        arguments = dict(context.message.arguments or {})
        auth = self._identity()
        outcome, code, result = "ok", None, None
        try:
            self._check(name, arguments, auth)
            result = await call_next(context)
            return result
        except Exception as error:  # noqa: BLE001 - toda salida de error pasa por aquí
            translated = self._translate(error)
            outcome, code = "error", translated.code
            if translated is error:
                raise
            raise translated from error
        finally:
            self._audit(name, arguments, auth, outcome, code, (time.perf_counter() - started) * 1000)

    # --- reglas -----------------------------------------------------------------------------------------------
    def _check(self, name: str, arguments: dict[str, Any], auth: Any) -> None:
        if name not in TOOL_SCOPES:
            if is_inventory_write_attempt(name):
                raise McpToolError(errors.READ_ONLY_VIOLATION,
                                   f"'{name}' intenta modificar el inventario. El inventario es de SOLO LECTURA en este "
                                   "servidor: la única operación disponible es inventory_get_stock.")
            return  # tool desconocida cualquiera: la rechaza FastMCP como "tool no encontrada"
        required = TOOL_SCOPES[name]
        granted = set(getattr(auth, "scopes", None) or [])
        if required not in granted:
            raise McpToolError(errors.FORBIDDEN_SCOPE,
                               f"La tool '{name}' requiere el scope '{required}', que el token no incluye.")
        unknown = set(arguments) - TOOL_ARGUMENTS[name]
        if unknown:
            if name in INVENTORY_TOOLS and unknown & _WRITE_ARGUMENTS:
                raise McpToolError(errors.READ_ONLY_VIOLATION,
                                   f"'{name}' es de solo lectura: se rechazan los argumentos {sorted(unknown)} porque "
                                   "intentan modificar el inventario.")
            raise McpToolError(errors.VALIDATION_ERROR,
                               f"Argumentos desconocidos para '{name}': {sorted(unknown)}. "
                               f"Admitidos: {sorted(TOOL_ARGUMENTS[name])}.")

    @staticmethod
    def _translate(error: Exception) -> McpToolError | Exception:
        if isinstance(error, McpToolError):
            return error
        text = str(error)
        if isinstance(error, FastMCPValidationError):  # argumentos que no cumplen el esquema de entrada
            return McpToolError(errors.VALIDATION_ERROR, " ".join(text.split())[:400])
        if isinstance(error, ToolError) and ("validation error" in text.lower() or "input" in text.lower()):
            return McpToolError(errors.VALIDATION_ERROR, text.removeprefix("Error calling tool: ").strip()[:400])
        if isinstance(error, ToolError) and "unknown tool" in text.lower():
            return error
        if isinstance(error, ToolError):
            return error
        logger.exception("Fallo interno en una tool MCP")
        return McpToolError("INTERNAL_ERROR", "Error interno del servidor MCP; consulta el log de auditoría.")

    # --- auditoría --------------------------------------------------------------------------------------------
    def _audit(self, tool: str, arguments: dict, auth: Any, outcome: str, code: str | None, ms: float) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": "tool_call",
            "tool": tool,
            "client_id": getattr(auth, "client_id", None),
            "subject": getattr(auth, "subject", None),
            "scopes": sorted(getattr(auth, "scopes", None) or []),
            "outcome": outcome,
            "error_code": code,
            "duration_ms": round(ms, 2),
            # Solo los NOMBRES de los argumentos y los ids/filtros; nunca textos libres ni el token.
            "arguments": {k: arguments[k] for k in ("ticket_id", "status", "product_id", "limit") if k in arguments},
            "argument_names": sorted(arguments),
        }
        audit_logger.info(json.dumps(record, ensure_ascii=False))
