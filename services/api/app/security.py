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

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------------------------- A01 · roles
# La autorización por rol y departamento vive en app/access/permissions.py (`require_access`): único punto de decisión.


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


# V4: el límite de 5 fallos ya NO es solo "por cuenta" (cualquiera podía bloquear a la víctima desde su propia IP): se aplica por
# pareja cuenta+IP, de modo que el atacante se bloquea a sí mismo y el dueño legítimo, desde otra IP, sigue entrando.
login_by_account_ip = RateLimiter(max_events=5, window_seconds=15 * 60)  # 5 fallos por cuenta e IP cada 15 min
login_by_account = RateLimiter(max_events=50, window_seconds=15 * 60)    # tope global por cuenta: frena la fuerza bruta distribuida
login_by_ip = RateLimiter(max_events=20, window_seconds=15 * 60)         # 20 fallos por IP (barrido de cuentas)
# V5: el resto de endpoints sensibles, que no tenían ningún límite.
sensitive_by_user = RateLimiter(max_events=5, window_seconds=15 * 60)    # 5 fallos de reautenticación por usuario (cambio de contraseña/email)
reset_by_ip = RateLimiter(max_events=10, window_seconds=15 * 60)         # 10 intentos de canje de token de recuperación por IP
telemetry_by_ip = RateLimiter(max_events=120, window_seconds=60)         # ingesta anónima: 120 lotes/min por IP
writes_per_minute = RateLimiter(max_events=30, window_seconds=60)        # escrituras críticas autenticadas: 30/min por usuario
forgot_by_ip = RateLimiter(max_events=5, window_seconds=15 * 60)
register_by_ip = RateLimiter(max_events=20, window_seconds=60 * 60)
# Endpoints que invocan a un modelo (coste por llamada): tope por usuario autenticado contra bucles de coste descontrolado.
model_per_minute = RateLimiter(max_events=20, window_seconds=60)        # ráfagas: 20 llamadas/minuto
model_per_hour = RateLimiter(max_events=200, window_seconds=60 * 60)    # sostenido: 200 llamadas/hora


def reset_rate_limits() -> None:
    for limiter in (login_by_account_ip, login_by_account, login_by_ip, sensitive_by_user, reset_by_ip, telemetry_by_ip, writes_per_minute,
                    forgot_by_ip, register_by_ip, model_per_minute, model_per_hour):
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


def limit_writes(current_user=Depends(get_current_user)) -> None:
    """Dependencia para escrituras críticas (alta/baja/cambio de proveedores, inventario y cuentas): 30 por minuto y usuario.
    Cuenta cada intento, así una sesión robada o un script descontrolado no puede vaciar ni inundar los datos."""
    key = f"user:{getattr(current_user, 'id', 'unknown')}"
    writes_per_minute.check(key)
    writes_per_minute.record(key)


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


# ------------------------------------------------------------------------------------------------- A04 · tamaño del cuerpo
MAX_BODY_BYTES = int(os.environ.get("MAX_BODY_BYTES", str(1024 * 1024)))          # 1 MiB para cualquier petición normal
UPLOAD_BODY_LIMITS = {"/api/incidents/analyze": 6 * 1024 * 1024}                    # CSV de análisis (MAX_CSV_BYTES = 5 MiB + multipart)


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """ASGI puro: rechaza con 413 los cuerpos que superan el tope, mirando `Content-Length` y también contando los bytes que
    llegan (chunked). Antes `/telemetry/events` leía 20 MB enteros en memoria sin autenticar (V6)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = UPLOAD_BODY_LIMITS.get(scope.get("path", ""), MAX_BODY_BYTES)
        declared = dict(scope.get("headers", [])).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            return await self._reject(send, limit)
        received = 0
        started = False

        async def counting_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message):
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge:
            if not started:
                await self._reject(send, limit)

    @staticmethod
    async def _reject(send, limit: int) -> None:
        body = b'{"detail":"El cuerpo de la petici\xc3\xb3n supera el tama\xc3\xb1o m\xc3\xa1ximo permitido"}'
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": body})


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
