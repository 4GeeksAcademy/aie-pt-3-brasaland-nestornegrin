"""Proveedor OAuth 2.0 / OIDC (Google). Solo intercambia el `code` por la identidad (`sub`, email): NO guarda tokens."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


class OAuthError(Exception):
    """El proveedor rechazó el `code` o no devolvió una identidad válida."""


@dataclass(frozen=True)
class ExternalIdentity:
    provider: str
    provider_user_id: str  # `sub`
    email: str
    email_verified: bool = False


class OAuthProvider(Protocol):
    name: str

    def is_configured(self) -> bool: ...
    def authorization_url(self, state: str, redirect_uri: str) -> str: ...
    def exchange_code(self, code: str, redirect_uri: str) -> ExternalIdentity: ...


def allowed_redirect_uris() -> set[str]:
    """Lista blanca: coincidencia EXACTA (sin comodines ni prefijos). `OAUTH_REDIRECT_URI` + `OAUTH_ALLOWED_REDIRECT_URIS` (coma)."""
    uris = {u.strip() for u in os.environ.get("OAUTH_ALLOWED_REDIRECT_URIS", "").split(",") if u.strip()}
    default = os.environ.get("OAUTH_REDIRECT_URI", "").strip()
    if default:
        uris.add(default)
    return uris


def default_redirect_uri() -> str | None:
    return os.environ.get("OAUTH_REDIRECT_URI", "").strip() or None


def federated_enabled() -> bool:
    """Interruptor por despliegue: en las tablets compartidas del local se pone `FEDERATED_AUTH_ENABLED=false`
    (dispositivo compartido + «Iniciar sesión con Google» = riesgo de mezcla de cuentas)."""
    return os.environ.get("FEDERATED_AUTH_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


class GoogleProvider:
    name = "google"

    def is_configured(self) -> bool:
        return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))

    def authorization_url(self, state: str, redirect_uri: str) -> str:
        query = urlencode({"client_id": os.environ["GOOGLE_CLIENT_ID"], "redirect_uri": redirect_uri, "response_type": "code",
                           "scope": "openid email", "state": state, "prompt": "select_account"})
        return f"{AUTH_URL}?{query}"

    def exchange_code(self, code: str, redirect_uri: str) -> ExternalIdentity:
        try:
            token = httpx.post(TOKEN_URL, timeout=10, data={
                "code": code, "client_id": os.environ["GOOGLE_CLIENT_ID"], "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
            token.raise_for_status()
            access_token = token.json()["access_token"]
            info = httpx.get(USERINFO_URL, timeout=10, headers={"Authorization": f"Bearer {access_token}"})
            info.raise_for_status()
            data = info.json()
            # El token solo vive en esta función: se usa una vez para leer la identidad y se descarta (no se persiste).
            return ExternalIdentity("google", str(data["sub"]), str(data.get("email", "")), bool(data.get("email_verified", False)))
        except (httpx.HTTPError, KeyError, ValueError) as error:
            raise OAuthError("Google no validó el código de autorización") from error


_providers: dict[str, OAuthProvider] = {"google": GoogleProvider()}


def get_oauth_provider_by_name(name: str) -> OAuthProvider | None:
    return _providers.get(name)
