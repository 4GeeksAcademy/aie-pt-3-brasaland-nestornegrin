"""Visor del audit log (solo lectura): no existe ninguna ruta POST/PUT/PATCH/DELETE sobre el registro."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import get_current_user

from . import scope
from .models import AuditFacets, AuditPage, VerifyResult


def create_audit_router() -> APIRouter:
    router = APIRouter(prefix="/audit-log", tags=["audit-log"])

    @router.get("", response_model=AuditPage)
    def list_entries(
        actor: str | None = Query(None, max_length=120, description="Coincidencia parcial con el id o el correo del actor."),
        actor_type: str | None = Query(None, pattern="^(user|agent|system|anonymous)$"),
        action: str | None = Query(None, max_length=80),
        category: str | None = Query(None, pattern="^(auth|access|federated|audit|process|data)$"),
        resource_type: str | None = Query(None, max_length=80),
        resource_id: str | None = Query(None, max_length=80),
        department: str | None = Query(None, max_length=60),
        outcome: str | None = Query(None, pattern="^(success|failure|denied)$"),
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        before_seq: int | None = Query(None, ge=1, description="Cursor: pide la página siguiente."),
        limit: int = Query(50, ge=1, le=200),
        current_user=Depends(get_current_user),
    ) -> AuditPage:
        from app.main import audit_log

        scope.require_viewer(current_user)
        items, total, next_cursor = audit_log.query(
            visible=scope.visibility(current_user), actor=actor, actor_type=actor_type, action=action, category=category,
            resource_type=resource_type, resource_id=resource_id, department=department, outcome=outcome,
            date_from=date_from, date_to=date_to, before_seq=before_seq, limit=limit)
        return AuditPage(items=items, total=total, limit=limit, next_before_seq=next_cursor)

    @router.get("/facets", response_model=AuditFacets)
    def facets(current_user=Depends(get_current_user)) -> AuditFacets:
        """Valores disponibles para los filtros, ya recortados al alcance del usuario (no revela acciones que no puede ver)."""
        from app.main import audit_log

        scope.require_viewer(current_user)
        actions, resources, categories = audit_log.facets(scope.visibility(current_user))
        return AuditFacets(actions=actions, resource_types=resources, categories=categories,
                           can_view_security=scope.can_view_security(current_user))

    @router.get("/verify", response_model=VerifyResult)
    def verify(current_user=Depends(get_current_user)) -> VerifyResult:
        """Recorre la cadena completa. `head_hash` se puede anclar fuera del servidor (p. ej. en un export semanal)."""
        from app.main import audit_log

        scope.require_platform_admin(current_user)
        return audit_log.verify()

    return router
