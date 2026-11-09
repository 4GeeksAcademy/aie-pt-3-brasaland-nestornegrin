"""Configuración del servidor MCP (todo por variables de entorno; nada de secretos en el código)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_TIMEOUT_SECONDS = 4.0  # por operación HTTP contra el backend
MCP_PATH = "/mcp"


class ConfigError(RuntimeError):
    """Falta una variable de entorno obligatoria."""


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Falta la variable de entorno {name}.")
    return value


@dataclass(frozen=True)
class Settings:
    """
    MCP_PUBLIC_URL         URL pública del endpoint MCP (el *resource identifier*), p. ej.
                           https://<codespace>-8001.app.github.dev/mcp . Es el `resource` de MCP Auth.
    OAUTH_ISSUER           issuer del proveedor OAuth/OIDC (Auth0: https://<tenant>.auth0.com/ — con barra final).
    OAUTH_AUDIENCE         `aud` que deben llevar los tokens (Auth0: el identifier de la API). Por defecto, MCP_PUBLIC_URL.
    MCP_BACKEND_BASE_URL   gestor de incidentes e inventario (services/api); por defecto http://localhost:8000.
    MCP_BACKEND_EMAIL/PASSWORD  cuenta de servicio con la que el servidor MCP lee/escribe en esa API.
    MCP_AUDIT_LOG          archivo JSONL con un registro por invocación de tool.
    MCP_ALLOWED_HOSTS      hosts permitidos (separados por coma) para la protección contra DNS rebinding.
    """

    public_url: str
    issuer: str
    audience: str
    backend_base_url: str = "http://localhost:8000"
    backend_email: str = ""
    backend_password: str = ""
    audit_log: Path = REPO_ROOT / "data" / "logs" / "mcp-audit.jsonl"
    allowed_hosts: tuple[str, ...] = field(default_factory=tuple)
    timeout: float = TOOL_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> "Settings":
        public_url = _required("MCP_PUBLIC_URL").rstrip("/")
        return cls(
            public_url=public_url,
            issuer=_required("OAUTH_ISSUER"),
            audience=os.environ.get("OAUTH_AUDIENCE", "").strip() or public_url,
            backend_base_url=(os.environ.get("MCP_BACKEND_BASE_URL") or "http://localhost:8000").rstrip("/"),
            backend_email=os.environ.get("MCP_BACKEND_EMAIL", ""),
            backend_password=os.environ.get("MCP_BACKEND_PASSWORD", ""),
            audit_log=Path(os.environ.get("MCP_AUDIT_LOG") or REPO_ROOT / "data" / "logs" / "mcp-audit.jsonl"),
            allowed_hosts=tuple(h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()),
        )
