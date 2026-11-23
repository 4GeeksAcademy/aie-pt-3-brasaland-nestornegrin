"""Servidor MCP de Brasaland: FastMCP (tools) + MCP Auth (OAuth 2.1 como *resource server*) en una app ASGI.

Transporte: **Streamable HTTP**, en modo sin estado (`stateless_http=True`). Se eligió HTTP y no stdio porque el
servidor debe poder usarlo VARIOS clientes remotos (otros agentes, otros equipos, partners), y OAuth solo tiene sentido
sobre HTTP: con stdio el servidor es un subproceso local de un único cliente y la autenticación se reduce a variables de
entorno (la especificación de MCP no define OAuth para stdio). El modo sin estado permite escalar en varias réplicas
sin sesiones pegajosas y hace que cada petición lleve su propio token.

Autenticación: NO se usa la capa de auth de FastMCP. MCP Auth (`mcpauth`) publica los *Protected Resource Metadata*
(`/.well-known/oauth-protected-resource/mcp`, que apuntan al servidor de autorización) y valida el JWT bearer de CADA
petición (firma con el JWKS del proveedor, issuer, audience y expiración). Sin token válido no se puede ni listar tools.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastmcp import FastMCP
from mcpauth import MCPAuth
from mcpauth.config import AuthServerConfig, AuthServerType
from mcpauth.types import ResourceServerConfig, ResourceServerMetadata
from mcpauth.utils import fetch_server_config
from starlette.applications import Starlette
from starlette.middleware import Middleware as ASGIMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .backend import IncidentsBackend, InventoryBackend
from .config import MCP_PATH, Settings
from .domain import ALL_SCOPES
from .middleware import AuditGuardMiddleware, configure_audit_log
from .tools import register_tools

logger = logging.getLogger(__name__)

INSTRUCTIONS = (
    "Servidor MCP de Brasaland. Gestiona tickets del gestor de incidentes (consultar, crear y cambiar de estado) y "
    "consulta el stock del inventario en SOLO LECTURA. Todas las tools exigen un access token OAuth con el scope indicado "
    "en su descripción (tickets:read, tickets:write, inventory:read). Los errores llevan un código entre corchetes, "
    "p. ej. [FORBIDDEN_SCOPE], [NOT_FOUND], [VALIDATION_ERROR], [READ_ONLY_VIOLATION]."
)


def build_mcp(settings: Settings, mcp_auth: MCPAuth, *, transport: httpx.AsyncBaseTransport | None = None) -> FastMCP:
    mcp = FastMCP("brasaland-mcp", instructions=INSTRUCTIONS)
    incidents = IncidentsBackend(settings.backend_base_url, settings.backend_email, settings.backend_password,
                                 settings.timeout, transport)
    inventory = InventoryBackend(settings.backend_base_url, settings.backend_email, settings.backend_password,
                                 settings.timeout, transport)
    register_tools(mcp, incidents, inventory)
    mcp.add_middleware(AuditGuardMiddleware(lambda: mcp_auth.auth_info))
    return mcp


def fetch_auth_server_config(issuer: str) -> AuthServerConfig:
    """Descubre los metadatos del proveedor (OIDC discovery: `<issuer>/.well-known/openid-configuration`)."""
    return fetch_server_config(issuer, AuthServerType.OIDC)


def build_mcp_auth(settings: Settings, auth_server: AuthServerConfig) -> MCPAuth:
    """MCP Auth como *resource server*: publica los metadatos del recurso protegido y apunta al proveedor OAuth."""
    return MCPAuth(protected_resources=ResourceServerConfig(metadata=ResourceServerMetadata(
        resource=settings.public_url,
        authorization_servers=[auth_server],
        scopes_supported=list(ALL_SCOPES),
        bearer_methods_supported=["header"],
        resource_name="Brasaland MCP (tickets e inventario)",
    )))


def create_app(
    settings: Settings,
    auth_server: AuthServerConfig,
    *,
    backend_transport: httpx.AsyncBaseTransport | None = None,
) -> Starlette:
    configure_audit_log(settings.audit_log)
    mcp_auth = build_mcp_auth(settings, auth_server)
    mcp = build_mcp(settings, mcp_auth, transport=backend_transport)
    bearer = mcp_auth.bearer_auth_middleware(
        "jwt", audience=settings.audience, resource=settings.public_url)  # sin token válido: 401 con WWW-Authenticate
    # Solo la app MCP lleva el middleware bearer; los metadatos del recurso (/.well-known/...) y /healthz son públicos.
    mcp_app = mcp.http_app(path=MCP_PATH, middleware=[ASGIMiddleware(bearer)], stateless_http=True,
                           allowed_hosts=list(settings.allowed_hosts) or None)

    async def health(_request) -> JSONResponse:  # sin datos de la compañía: solo para saber que el proceso vive
        return JSONResponse({"status": "ok"})

    app = Starlette(
        routes=[
            Route("/healthz", health),
            *mcp_auth.resource_metadata_router().routes,  # /.well-known/oauth-protected-resource/<path>
            Mount("/", app=mcp_app),
        ],
        lifespan=mcp_app.lifespan,
    )
    app.state.mcp_auth = mcp_auth
    return app


def create_app_from_env() -> Starlette:
    settings = Settings.from_env()
    return create_app(settings, fetch_auth_server_config(settings.issuer))
