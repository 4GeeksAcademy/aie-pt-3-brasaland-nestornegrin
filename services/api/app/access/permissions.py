"""Verificación de permisos CENTRALIZADA (único punto de decisión de acceso de la API).

Orden de evaluación (BRIEFING): primero el ROL, después el DEPARTAMENTO.
  1. Rol insuficiente            → 403 «insufficient_role»  (nunca un 200 con datos vacíos)
  2. Departamento ajeno          → 403 «department_scope»   (salvo capacidad `cross_department`, privilegio de rol Admin)

Las rutas NO repiten esta lógica: declaran lo que exponen con `Depends(require_access(Action.X, department=...))`.
"""

from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, Request, status

from app.auth.dependencies import get_current_user

from .models import CROSS_DEPARTMENT, Action

DepartmentRef = str | Callable[[Request], "str | None"] | None


def _forbidden(code: str, message: str, **extra: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message, headers={"X-Access-Denied": code, **extra})


def authorize(user, action: Action, department: str | None = None) -> None:
    """Decide si `user` puede ejecutar `action` (sobre datos de `department`, si se indica). Lanza 403 explícito si no."""
    from app.main import access_catalog  # import tardío: main crea el catálogo

    if action.value not in user.capabilities:
        needed = access_catalog.minimum_role_for(action.value)
        needed_text = f"requiere el rol «{needed['code']}» o superior" if needed else "no está habilitada para ningún rol"
        raise _forbidden("insufficient_role",
                         f"Tu rol «{user.role}» no permite «{action.value}»: {needed_text}.")
    if department is None or CROSS_DEPARTMENT in user.capabilities:
        return
    if user.department is None:
        raise _forbidden("department_scope", "No tienes un departamento asignado: un Admin debe asignártelo para ver datos departamentales.")
    if user.department != department:
        raise _forbidden("department_scope",
                         f"Estos datos pertenecen al departamento «{department}»; tu departamento es «{user.department}».")


def require_access(action: Action, department: DepartmentRef = None):
    """Dependencia de FastAPI: sesión válida + `authorize`. `department` puede ser un código fijo o una función
    `(request) -> código` para recursos cuyo departamento sale del propio registro (p. ej. `/internal-reports/{id}`)."""

    def dependency(request: Request, current_user=Depends(get_current_user)):
        scope = department(request) if callable(department) else department
        authorize(current_user, action, scope)
        return current_user

    return dependency


def visible_department_id(user) -> int | None:
    """Alcance de un LISTADO departamental: None = todos los departamentos (Admin); si no, solo el del usuario.
    Es alcance (filtrado), no una denegación silenciosa: la capacidad `read` ya se comprobó con `require_access`; sin departamento → 403."""
    if CROSS_DEPARTMENT in user.capabilities:
        return None
    if user.department_id is None:
        raise _forbidden("department_scope", "No tienes un departamento asignado: un Admin debe asignártelo para ver datos departamentales.")
    return user.department_id


# Departamentos de las RFP (data/pipelines/rfp_intake) → códigos del catálogo de acceso.
RFP_DEPARTMENT_TO_ACCESS = {
    "marketing": "marketing",
    "operaciones": "restaurant_operations",
    "procurement": "procurement",
    "training": "training_quality",
}

# Departamento propietario de cada módulo de datos existente (BRIEFING: "datos que pertenecen a este departamento").
OPS = "restaurant_operations"      # incidentes de local, reportes de turno, inventario de cocina
PROCUREMENT = "procurement"        # proveedores, tarifas
TECHNOLOGY = "technology"          # telemetría / configuración de plataforma
