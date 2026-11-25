"""Rutas de administración de acceso: /roles, /departments (solo Admin) y /internal-reports (alcance departamental)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .catalog import CatalogError
from .models import (
    Action,
    DepartmentCreate,
    DepartmentOut,
    DepartmentUpdate,
    InternalReportCreate,
    InternalReportOut,
    InternalReportUpdate,
    RoleCreate,
    RoleOut,
    RoleUpdate,
)
from .permissions import authorize, require_access, visible_department_id


def _catalog():
    from app.main import access_catalog

    return access_catalog


def _reports():
    from app.main import internal_report_repository

    return internal_report_repository


def _raise(error: CatalogError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=str(error))


def _report_out(row: dict) -> InternalReportOut:
    department = _catalog().get_department(row["department_id"])
    return InternalReportOut(**row, department=department["code"] if department else "")


def _report_department(request: Request) -> str:
    """Departamento del registro pedido por id (el alcance sale del propio dato). 404 si no existe."""
    row = _reports().get(request.path_params["report_id"])
    if row is None:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    department = _catalog().get_department(row["department_id"])
    return department["code"] if department else ""


def create_router() -> APIRouter:
    router = APIRouter(tags=["access"])
    admin = [Depends(require_access(Action.ADMINISTER))]

    # ------------------------------------------------------------------ roles (Admin)
    @router.get("/roles", response_model=list[RoleOut], dependencies=admin)
    def list_roles() -> list[RoleOut]:
        return [RoleOut.model_validate(r) for r in _catalog().list_roles()]

    @router.post("/roles", response_model=RoleOut, status_code=201, dependencies=admin)
    def create_role(payload: RoleCreate) -> RoleOut:
        try:
            return RoleOut.model_validate(_catalog().create_role(payload.model_dump()))
        except CatalogError as error:
            raise _raise(error)

    @router.get("/roles/{role_id}", response_model=RoleOut, dependencies=admin)
    def get_role(role_id: int) -> RoleOut:
        role = _catalog().get_role(role_id)
        if role is None:
            raise HTTPException(status_code=404, detail="Rol no encontrado")
        return RoleOut.model_validate(role)

    @router.put("/roles/{role_id}", response_model=RoleOut, dependencies=admin)
    def update_role(role_id: int, payload: RoleUpdate) -> RoleOut:
        role = _catalog().update_role(role_id, payload.model_dump(exclude_none=True))
        if role is None:
            raise HTTPException(status_code=404, detail="Rol no encontrado")
        return RoleOut.model_validate(role)

    # ------------------------------------------------------------------ departamentos (Admin)
    @router.get("/departments", response_model=list[DepartmentOut], dependencies=admin)
    def list_departments() -> list[DepartmentOut]:
        return [DepartmentOut.model_validate(d) for d in _catalog().list_departments()]

    @router.post("/departments", response_model=DepartmentOut, status_code=201, dependencies=admin)
    def create_department(payload: DepartmentCreate) -> DepartmentOut:
        try:
            return DepartmentOut.model_validate(_catalog().create_department(payload.model_dump()))
        except CatalogError as error:
            raise _raise(error)

    @router.get("/departments/{department_id}", response_model=DepartmentOut, dependencies=admin)
    def get_department(department_id: int) -> DepartmentOut:
        department = _catalog().get_department(department_id)
        if department is None:
            raise HTTPException(status_code=404, detail="Departamento no encontrado")
        return DepartmentOut.model_validate(department)

    @router.put("/departments/{department_id}", response_model=DepartmentOut, dependencies=admin)
    def update_department(department_id: int, payload: DepartmentUpdate) -> DepartmentOut:
        department = _catalog().update_department(department_id, payload.model_dump(exclude_none=True))
        if department is None:
            raise HTTPException(status_code=404, detail="Departamento no encontrado")
        return DepartmentOut.model_validate(department)

    # ------------------------------------------------------------------ internal-reports (alcance departamental)
    @router.get("/internal-reports", response_model=list[InternalReportOut])
    def list_reports(current_user=Depends(require_access(Action.READ)),
                     department: str | None = Query(default=None, description="Solo Admin: filtra por código de departamento.")) -> list[InternalReportOut]:
        """Listado con ALCANCE: Empleado/Supervisor reciben solo su departamento; Admin, todos (o el filtrado)."""
        scope = visible_department_id(current_user)
        if department is not None:
            wanted = _catalog().get_department_by_code(department)
            if wanted is None:
                raise HTTPException(status_code=404, detail="Departamento no encontrado")
            authorize(current_user, Action.READ, department)  # pedir otro departamento sin ser Admin → 403
            scope = wanted["id"]
        return [_report_out(r) for r in _reports().list(scope)]

    @router.post("/internal-reports", response_model=InternalReportOut, status_code=201)
    def create_report(payload: InternalReportCreate, current_user=Depends(require_access(Action.CREATE))) -> InternalReportOut:
        department_id = payload.department_id or current_user.department_id
        if department_id is None:
            raise HTTPException(status_code=403, detail="No tienes un departamento asignado: indica uno o pide a un Admin que te lo asigne.")
        department = _catalog().get_department(department_id)
        if department is None:
            raise HTTPException(status_code=422, detail="El departamento indicado no existe")
        authorize(current_user, Action.CREATE, department["code"])  # crear en otro departamento sin ser Admin → 403
        return _report_out(_reports().create(department_id, payload.title, payload.body, current_user.id))

    @router.get("/internal-reports/{report_id}", response_model=InternalReportOut,
                dependencies=[Depends(require_access(Action.READ, _report_department))])
    def get_report(report_id: str) -> InternalReportOut:
        return _report_out(_reports().get(report_id))

    @router.put("/internal-reports/{report_id}", response_model=InternalReportOut,
                dependencies=[Depends(require_access(Action.UPDATE, _report_department))])
    def update_report(report_id: str, payload: InternalReportUpdate) -> InternalReportOut:
        return _report_out(_reports().update(report_id, payload.model_dump(exclude_none=True)))

    @router.post("/internal-reports/{report_id}/approve", response_model=InternalReportOut)
    def approve_report(report_id: str, current_user=Depends(require_access(Action.APPROVE, _report_department))) -> InternalReportOut:
        return _report_out(_reports().update(report_id, {"approved_by": current_user.id,
                                                          "approved_at": datetime.now(timezone.utc).isoformat()}))

    @router.delete("/internal-reports/{report_id}", status_code=204, response_model=None,
                   dependencies=[Depends(require_access(Action.DELETE, _report_department))])
    def delete_report(report_id: str) -> None:
        _reports().delete(report_id)

    return router
