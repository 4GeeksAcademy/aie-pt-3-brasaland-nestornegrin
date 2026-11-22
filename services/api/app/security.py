"""Controles de seguridad transversales de la API (auditoría OWASP Top 10, docs/security/owasp-top10-audit.md).

- A01  `require_roles`: autorización por rol (una sesión válida NO basta para modificar proveedores o inventario) y
       `bind_actor`: el actor del agente sale del token, no de lo que declare el cliente.
- A04/A07  `RateLimiter`: límite de intentos en login, recuperación de contraseña y registro (en memoria, por proceso).
- A05  `allowed_origins` (CORS y WebSocket con la misma lista exacta, sin comodines de terceros) y `SecurityHeadersMiddleware`.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import deque
from typing import Callable

from fastapi import Depends, HTTPException, Request, status

from app.auth.dependencies import get_current_user
from app.auth.models import UserRole

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------------------------- A01 · roles
def require_roles(*roles: UserRole):
    """Dependencia: exige sesión válida Y uno de los roles indicados (403 si no)."""
    allowed = set(roles)

    def dependency(current_user=Depends(get_current_user)):
        if current_user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tu rol no permite realizar esta acción")
        return current_user

    return dependency


MANAGE_ROLES = (UserRole.MANAGER, UserRole.ADMIN)
require_manager_or_admin = require_roles(*MANAGE_ROLES)


def bind_actor(request: Request, current_user=Depends(get_current_user)):
    """Exige sesión y fija `request.state.actor` con la identidad autenticada (para auditar al agente sin fiarse del cliente)."""
    request.state.actor = f"user:{current_user.id}"
    return current_user


def require_confirmation(confirm: bool, action: str) -> None:
    """Acción irreversible (BRIEFING §5): sin `?confirm=true` explícito se responde 428 y no se hace nada."""
    if not confirm:
        raise HTTPException(status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                            detail=f"{action} es una acción irreversible: confírmala con confirm=true.")


# ------------------------------------------------------------------------------------------------- A04/A07 · límites
class RateLimiter:
    """Ventana deslizante en memoria: como mucho `max_events` por `key` en `window_seconds`. Válido para un solo proceso."""

    MAX_KEYS = 10_000

    def __init__(self, max_events: int, window_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.max_events, self.window, self._clock = max_events, window_seconds, clock
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        events = self._events.setdefault(key, deque())
        while events and now - events[0] > self.window:
            events.popleft()
        if not events:
            self._events.pop(key, None)
        return events

    def retry_after(self, key: str) -> int:
        """Segundos hasta poder volver a intentarlo (0 si no está bloqueada)."""
        with self._lock:
            now = self._clock()
            events = self._prune(key, now)
            if len(events) < self.max_events:
                return 0
            return max(1, int(self.window - (now - events[0])) + 1)

    def check(self, key: str) -> None:
        wait = self.retry_after(key)
        if wait:
            logger.warning("rate_limited key=%s retry_after=%ss", hashlib.sha256(key.encode()).hexdigest()[:12], wait)  # A09
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                detail="Demasiados intentos. Inténtalo de nuevo más tarde.", headers={"Retry-After": str(wait)})

    def record(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            if len(self._events) > self.MAX_KEYS:  # tope de memoria ante un barrido con miles de claves
                self._events.clear()
            self._events.setdefault(key, deque()).append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


login_by_account = RateLimiter(max_events=5, window_seconds=15 * 60)     # 5 fallos por cuenta cada 15 min
login_by_ip = RateLimiter(max_events=20, window_seconds=15 * 60)         # 20 fallos por IP (barrido de cuentas)
forgot_by_ip = RateLimiter(max_events=5, window_seconds=15 * 60)
register_by_ip = RateLimiter(max_events=20, window_seconds=60 * 60)
# Endpoints que invocan a un modelo (coste por llamada): tope por usuario autenticado contra bucles de coste descontrolado.
model_per_minute = RateLimiter(max_events=20, window_seconds=60)        # ráfagas: 20 llamadas/minuto
model_per_hour = RateLimiter(max_events=200, window_seconds=60 * 60)    # sostenido: 200 llamadas/hora


def reset_rate_limits() -> None:
    for limiter in (login_by_account, login_by_ip, forgot_by_ip, register_by_ip, model_per_minute, model_per_hour):
        limiter.reset()


def limit_model_calls(current_user=Depends(get_current_user)) -> None:
    """Dependencia para toda ruta que dispare una llamada a un modelo (NIST Protect / OWASP A04): 429 al pasar el tope.
    Se comprueba ANTES de ejecutar la ruta, así una petición rechazada no gasta tokens."""
    user_id = current_user.get("id") if isinstance(current_user, dict) else getattr(current_user, "id", None)
    key = f"user:{user_id if user_id is not None else 'unknown'}"
    model_per_minute.check(key)
    model_per_hour.check(key)
    model_per_minute.record(key)
    model_per_hour.record(key)


def consume_model_budget(user_key: str) -> int:
    """Versión sin excepciones para canales que no son HTTP (WebSocket): 0 si se permite (y se contabiliza); si no, los segundos a esperar."""
    wait = max(model_per_minute.retry_after(user_key), model_per_hour.retry_after(user_key))
    if wait:
        logger.warning("rate_limited channel=ws key=%s retry_after=%ss", hashlib.sha256(user_key.encode()).hexdigest()[:12], wait)
        return wait
    model_per_minute.record(user_key)
    model_per_hour.record(user_key)
    return 0


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ------------------------------------------------------------------------------------------------- A05 · origen y cabeceras
def allowed_origins() -> list[str]:
    """Orígenes del frontend: lista EXACTA (nada de `*.app.github.dev`, que admitiría el Codespace de cualquiera).

    En un Codespace propio se añaden sus URLs reenviadas (`CODESPACE_NAME` y el dominio de reenvío los define GitHub)."""
    origins = ["http://localhost:3000", "http://localhost:3001"]
    if os.environ.get("FRONTEND_URL"):
        origins.append(os.environ["FRONTEND_URL"].rstrip("/"))
    codespace, domain = os.environ.get("CODESPACE_NAME"), os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev")
    if codespace:
        origins += [f"https://{codespace}-3000.{domain}", f"https://{codespace}-3001.{domain}"]
    origins += [o.strip().rstrip("/") for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    return list(dict.fromkeys(origins))


def docs_enabled() -> bool:
    """Swagger/ReDoc/OpenAPI se apagan en producción (`APP_ENV=production`): no hay motivo para publicar el mapa de la API."""
    return os.environ.get("APP_ENV", "development").lower() != "production"


_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")
_BASE_HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
    b"referrer-policy": b"no-referrer",
    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
}
_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")


class SecurityHeadersMiddleware:
    """ASGI puro (sin buffering: no interfiere con el streaming SSE). Añade cabeceras sin pisar las que ya fije la ruta."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                extra = dict(_BASE_HEADERS)
                if not path.startswith(_DOC_PATHS):
                    extra[_CSP[0]] = _CSP[1]
                extra.setdefault(b"cache-control", b"no-store")
                if scope.get("scheme") == "https":
                    extra[b"strict-transport-security"] = b"max-age=31536000; includeSubDomains"
                headers += [(name, value) for name, value in extra.items() if name not in present]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
