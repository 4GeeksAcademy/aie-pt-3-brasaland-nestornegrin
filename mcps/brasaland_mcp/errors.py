"""Códigos de error del servidor MCP. Cada familia de fallo tiene un código y un mensaje distintos entre sí.

Fallos de AUTENTICACIÓN (sin token válido) se rechazan antes de llegar al protocolo MCP, con HTTP 401 y cabecera
`WWW-Authenticate: Bearer error="..." resource_metadata="..."` (lo hace MCP Auth). Los demás viajan como errores de
tool (`isError: true`) con el texto `[CODIGO] mensaje`, para que un cliente pueda distinguirlos sin ambigüedad.

    HTTP 401  missing_auth_header / invalid_auth_header_format / missing_bearer_token   no hay token utilizable
    HTTP 401  invalid_token / token_verification_failed / invalid_issuer / invalid_audience / expired  token no válido
    HTTP 403  missing_required_scopes                                                   falta un scope exigido a todo el servidor

    [FORBIDDEN_SCOPE]        token válido, pero sin el scope que exige ESTA tool (autorización)
    [READ_ONLY_VIOLATION]    intento de modificar el inventario (el inventario es de solo lectura)
    [VALIDATION_ERROR]       argumentos inválidos (tipo, rango, valor de dominio, campo desconocido)
    [NOT_FOUND]              el ticket o el producto no existe
    [INVALID_TRANSITION]     el ciclo de vida del ticket no permite ese cambio de estado
    [BACKEND_UNAUTHORIZED]   el servidor MCP no pudo autenticarse contra el gestor de incidentes / inventario
    [BACKEND_TIMEOUT]        el backend no respondió a tiempo
    [BACKEND_UNAVAILABLE]    el backend está caído o respondió algo inesperado
"""
from __future__ import annotations

from fastmcp.exceptions import ToolError

FORBIDDEN_SCOPE = "FORBIDDEN_SCOPE"
READ_ONLY_VIOLATION = "READ_ONLY_VIOLATION"
VALIDATION_ERROR = "VALIDATION_ERROR"
NOT_FOUND = "NOT_FOUND"
INVALID_TRANSITION = "INVALID_TRANSITION"
BACKEND_UNAUTHORIZED = "BACKEND_UNAUTHORIZED"
BACKEND_TIMEOUT = "BACKEND_TIMEOUT"
BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"

ERROR_CODES = {
    FORBIDDEN_SCOPE: "token válido sin el scope que exige la tool",
    READ_ONLY_VIOLATION: "intento de modificar un recurso de solo lectura",
    VALIDATION_ERROR: "argumentos inválidos",
    NOT_FOUND: "el recurso no existe",
    INVALID_TRANSITION: "cambio de estado no permitido por el ciclo de vida",
    BACKEND_UNAUTHORIZED: "el servidor no pudo autenticarse contra el backend",
    BACKEND_TIMEOUT: "el backend no respondió a tiempo",
    BACKEND_UNAVAILABLE: "el backend no está disponible",
}


class McpToolError(ToolError):
    """Error de tool con código estable: el texto que ve el cliente es `[CODIGO] mensaje`."""

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.detail = message


def error_code_of(error: BaseException) -> str:
    return error.code if isinstance(error, McpToolError) else "INTERNAL_ERROR"
