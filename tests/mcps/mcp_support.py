"""Soportes de las pruebas del servidor MCP: un proveedor OAuth local (claves RSA + JWKS + metadatos OIDC) para firmar
tokens de prueba, un backend HTTP falso y un arranque real del servidor (uvicorn en un hilo) para probarlo por HTTP.

El proveedor OAuth local SOLO existe en las pruebas: el servidor valida firma, issuer, audience y expiración igual que
con Auth0 (mismo código de MCP Auth).
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from mcpauth.config import AuthorizationServerMetadata, AuthServerConfig, AuthServerType
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcps.brasaland_mcp.config import Settings
from mcps.brasaland_mcp.domain import ALL_SCOPES
from mcps.brasaland_mcp.server import create_app

TICKETS = [
    {"id": 94, "title": "Nevera averiada", "description": "La nevera 2 no enfría.", "category": "Fallo operativo",
     "origin": "branch", "branch": "Brasaland Laureles", "status": "open",
     "created_at": "2026-11-01T10:00:00+00:00", "updated_at": "2026-11-01T10:00:00+00:00"},
    {"id": 90, "title": "Incidencia histórica", "description": "Queja antigua.", "category": "Queja",
     "origin": "customer", "branch": "central", "status": "resolved",
     "created_at": "2026-10-01T10:00:00+00:00", "updated_at": "2026-10-02T10:00:00+00:00"},
]
PRODUCTS = [
    {"id": 1, "name": "Pollo entero", "sku": "POL-001", "restaurant": "Brasaland Laureles", "current_stock": 42.0},
    {"id": 2, "name": "Carbón vegetal", "sku": "CAR-001", "restaurant": "Brasaland Laureles", "current_stock": 15.5},
]
TRANSITIONS = {"open": {"in_progress", "discarded"}, "in_progress": {"resolved", "discarded"}, "resolved": set(),
               "discarded": set()}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class FakeBackendApi:
    """Imita los endpoints reales del gestor de incidentes y de inventario y registra cada petición."""

    def __init__(self):
        self.tickets = [dict(t) for t in TICKETS]
        self.requests: list[tuple[str, str]] = []
        self.mode = "ok"  # ok | timeout | down

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if self.mode == "timeout":
            raise httpx.ReadTimeout("simulado", request=request)
        if self.mode == "down":
            raise httpx.ConnectError("simulado", request=request)
        path = request.url.path
        if path == "/auth/login":
            return httpx.Response(200, json={"access_token": "jwt-backend"})
        if request.headers.get("authorization") != "Bearer jwt-backend":
            return httpx.Response(401, json={"detail": "Credenciales inválidas"})
        if path == "/inventory/products" and request.method == "GET":
            return httpx.Response(200, json=PRODUCTS)
        if path == "/api/incidents" and request.method == "GET":
            status = request.url.params.get("status")
            return httpx.Response(200, json=[t for t in self.tickets if not status or t["status"] == status])
        if path == "/api/incidents" and request.method == "POST":
            body = json.loads(request.content)
            if body.get("branch") not in {"central", "Brasaland Laureles"}:
                return httpx.Response(400, json={"detail": [{"loc": ["body", "branch"], "msg": "valor no válido"}]})
            new = {**body, "id": 100 + len(self.tickets), "status": "open",
                   "created_at": "2026-11-09T10:00:00+00:00", "updated_at": "2026-11-09T10:00:00+00:00"}
            self.tickets.append(new)
            return httpx.Response(201, json=new)
        if path.startswith("/api/incidents/"):
            parts = path.split("/")
            found = next((t for t in self.tickets if str(t["id"]) == parts[3]), None)
            if found is None:
                return httpx.Response(404, json={"detail": "Incidencia no encontrada"})
            if request.method == "PATCH" and path.endswith("/status"):
                new_status = json.loads(request.content)["status"]
                if new_status != found["status"] and new_status not in TRANSITIONS[found["status"]]:
                    return httpx.Response(400, json={"detail": f"No se puede pasar de '{found['status']}' a '{new_status}'."})
                found["status"] = new_status
                return httpx.Response(200, json=found)
            if request.method == "GET" and len(parts) == 4:
                return httpx.Response(200, json=found)
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


class LocalIssuer:
    """Proveedor OAuth/OIDC mínimo para pruebas: genera claves RSA, publica su JWKS y firma tokens."""

    def __init__(self, port: int, audience: str):
        self.issuer = f"http://127.0.0.1:{port}/"
        self.audience = audience
        self.port = port
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(RSAAlgorithm.to_jwk(self._key.public_key()))
        jwk.update({"kid": "test-key", "use": "sig", "alg": "RS256"})
        self.jwks = {"keys": [jwk]}

    def metadata(self) -> AuthServerConfig:
        return AuthServerConfig(type=AuthServerType.OIDC, metadata=AuthorizationServerMetadata(
            issuer=self.issuer, authorization_endpoint=f"{self.issuer}authorize", token_endpoint=f"{self.issuer}token",
            jwks_uri=f"{self.issuer}.well-known/jwks.json", response_types_supported=["code"],
            scopes_supported=list(ALL_SCOPES)))

    def token(self, *, scopes=ALL_SCOPES, audience=None, issuer=None, client_id="cliente-de-prueba",
              expires_in=300, key=None) -> str:
        now = int(time.time())
        claims = {"iss": issuer or self.issuer, "aud": audience or self.audience, "sub": f"{client_id}@clients",
                  "azp": client_id, "iat": now, "exp": now + expires_in, "scope": " ".join(scopes)}
        return jwt.encode(claims, key or self._key, algorithm="RS256", headers={"kid": "test-key"})

    def other_key(self):
        return rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def app(self) -> Starlette:
        async def jwks(_request):
            return JSONResponse(self.jwks)

        return Starlette(routes=[Route("/.well-known/jwks.json", jwks)])


class ServerThread:
    def __init__(self, app, port: int):
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("el servidor de pruebas no arrancó")

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=5)


@contextmanager
def running_mcp_server(tmp_path: Path, backend: FakeBackendApi, **settings_overrides):
    """Servidor MCP real (uvicorn) con un proveedor OAuth local y un backend falso. Devuelve (url, issuer, audit_log)."""
    mcp_port, issuer_port = free_port(), free_port()
    public_url = f"http://127.0.0.1:{mcp_port}/mcp"
    issuer = LocalIssuer(issuer_port, audience=public_url)
    audit_log = tmp_path / "audit.jsonl"
    settings = Settings(public_url=public_url, issuer=issuer.issuer, audience=public_url,
                        backend_base_url="http://backend.test", backend_email="mcp@brasaland.test",
                        backend_password="clave-de-servicio", audit_log=audit_log, **settings_overrides)
    app = create_app(settings, issuer.metadata(), backend_transport=backend.transport())
    with ServerThread(issuer.app(), issuer_port), ServerThread(app, mcp_port):
        yield public_url, issuer, audit_log
