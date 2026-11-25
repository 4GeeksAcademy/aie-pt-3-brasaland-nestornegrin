"""Middleware ASGI: registra cada acción del inventario (`catalog.AUDITED_ROUTES`) y TODA denegación 403, sea cual sea la ruta.

Se hace aquí y no en cada manejador para que sea imposible «olvidarse» de auditar: añadir una ruta que modifica datos sin
entrar en el inventario hace fallar `test_toda_ruta_que_modifica_datos_esta_inventariada`.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .catalog import AUDITED_ROUTES
from .log import AuditLog
from .recorder import actor_fields

logger = logging.getLogger("brasaland.audit")
MAX_CAPTURED_BODY = 65_536


class _State:
    """Acceso a `scope['state']` (donde los manejadores dejan `note`) sin construir un Request."""

    def __init__(self, scope: Scope) -> None:
        self._data = scope.setdefault("state", {})

    def get(self, name: str, default: Any = None) -> Any:
        return self._data.get(name, default)


def _outcome(status_code: int, category: str) -> str:
    if status_code < 400:
        return "success"
    if status_code == 403 or (status_code == 401 and category not in ("auth", "federated")):
        return "denied"
    return "failure"


class AuditMiddleware:
    def __init__(self, app: ASGIApp, log: AuditLog) -> None:
        self.app, self.log = app, log

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        captured: dict[str, Any] = {"status": 500, "denied": None, "body": b""}

        async def tap(message: Message) -> None:
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]
                for key, value in message.get("headers", []):
                    if key.lower() == b"x-access-denied":
                        captured["denied"] = value.decode()
            elif message["type"] == "http.response.body" and len(captured["body"]) < MAX_CAPTURED_BODY:
                captured["body"] += message.get("body", b"")
            await send(message)

        try:
            await self.app(scope, receive, tap)
        finally:
            try:
                await run_in_threadpool(self._record, scope, captured)
            except Exception:  # noqa: BLE001 - la acción ya ocurrió: no se la tapa, pero el fallo del registro queda a gritos
                logger.critical("No se pudo escribir en el audit log (%s %s)", scope.get("method"), scope.get("path"), exc_info=True)

    # ------------------------------------------------------------------
    def _record(self, scope: Scope, captured: dict[str, Any]) -> None:
        route = scope.get("route")
        template = getattr(route, "path", None) or scope.get("path", "")
        method = scope["method"]
        spec = AUDITED_ROUTES.get((method, template))
        status_code = captured["status"]
        denied = status_code == 403
        if spec is None and not denied:
            return
        state = _State(scope)
        user = state.get("audit_user")
        client = scope.get("client")
        origin = client[0] if client else "unknown"  # misma fuente que `security.client_ip` (peer de la conexión; no se fía de cabeceras)
        params = scope.get("path_params") or {}
        resource_id = state.get("audit_resource_id") or (str(next(iter(params.values()))) if params else None)
        if spec and spec.id_from_body and not resource_id and status_code < 300:
            resource_id = _id_from_body(captured["body"], spec.id_from_body)
        details = {"method": method, "route": template, "http_status": status_code, **(state.get("audit_details") or {})}
        if captured["denied"]:
            details["denied_reason"] = captured["denied"]
        if spec is None:  # denegación en una ruta fuera del inventario (p. ej. un GET de datos que el usuario no puede ver)
            action, category, resource_type, department = "access.denied", "access", template, None
        else:
            action, category, resource_type, department = spec.action, spec.category, spec.resource_type, spec.department
            if denied:
                details["denied_reason"] = captured["denied"] or "forbidden"
        self.log.append(**actor_fields(user, state.get("audit_label")), action=action, category=category, resource_type=resource_type,
                        resource_id=resource_id, department=state.get("audit_department") or department,
                        outcome=_outcome(status_code, category), origin=origin, channel="http", details=details)


def _id_from_body(body: bytes, key: str) -> str | None:
    try:
        value = json.loads(body).get(key)
    except (ValueError, AttributeError):
        return None
    return None if value is None else str(value)
