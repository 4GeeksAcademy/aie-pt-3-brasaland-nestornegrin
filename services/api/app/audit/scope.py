"""Quién puede ver qué en el visor. «No todo Admin debe ver necesariamente todo» (contexto de la empresa).

  * Empleado (rango 1)                 → nada: el visor no es para él (403).
  * Supervisor y Admin de un departamento → SOLO acciones sobre datos de negocio de SU departamento.
  * Admin de Tecnología                 → todo, incluidos los eventos de seguridad (login, permisos, identidades federadas, procesos).
Un Admin de Procurement, por ejemplo, ve lo que ocurrió con los proveedores pero no los inicios de sesión ni los cambios de rol.
"""

from __future__ import annotations

from typing import Callable

from fastapi import HTTPException, status

from app.access.permissions import has_min_rank, is_platform_admin

from .models import AuditEntry

MIN_VIEWER_RANK = 2  # Supervisor


def _denied(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message, headers={"X-Access-Denied": "audit_scope"})


def can_view_security(user) -> bool:
    return is_platform_admin(user)


def require_viewer(user) -> None:
    if not has_min_rank(user, MIN_VIEWER_RANK):
        raise _denied("El registro de auditoría requiere el rol Supervisor o superior.")
    if not can_view_security(user) and user.department is None:
        raise _denied("No tienes un departamento asignado: un Admin debe asignártelo para consultar la auditoría.")


def require_platform_admin(user) -> None:
    if not can_view_security(user):
        raise _denied("Verificar la integridad del registro es una acción de Admin del departamento de Tecnología.")


def visibility(user) -> Callable[[AuditEntry], bool]:
    if can_view_security(user):
        return lambda entry: True
    department = user.department
    return lambda entry: entry.category == "data" and (entry.department or entry.actor_department) == department
