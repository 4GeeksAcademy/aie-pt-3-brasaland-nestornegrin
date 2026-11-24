from fastapi import APIRouter, Depends, HTTPException, Request

from app.access.models import Action, AssignmentUpdate
from app.access.permissions import authorize, require_access
from app.audit.recorder import note
from app.auth.dependencies import get_current_user
from app.auth.models import AdminUserCreate, RegisterResponse, UserListItem, UserResponse, UserUpdate
from app.auth.security import hash_password


def _is_self_or(action: Action):
    """Dependencia: la propia cuenta, o quien tenga la capacidad `action` (Admin para ver/editar a otros)."""

    def dependency(user_id: int, current_user=Depends(get_current_user)):
        if current_user.id != user_id:
            authorize(current_user, action)
        return current_user

    return dependency


def create_router() -> APIRouter:
    router = APIRouter(prefix="/users", tags=["users"])

    @router.post("", response_model=RegisterResponse, status_code=201, dependencies=[Depends(require_access(Action.ADMINISTER))])
    def create_user(payload: AdminUserCreate, request: Request) -> RegisterResponse:
        """Alta por un Admin, eligiendo rol y departamento. El registro público es POST /auth/register."""
        from app.main import access_catalog, profile_repository, user_repository

        email = str(payload.email).lower()
        if user_repository.get_by_email(email):
            raise HTTPException(status_code=409, detail="El email ya está registrado")
        role_id = payload.role_id
        if role_id is not None and access_catalog.get_role(role_id) is None:
            raise HTTPException(status_code=422, detail="El rol indicado no existe")
        if payload.department_id is not None and access_catalog.get_department(payload.department_id) is None:
            raise HTTPException(status_code=422, detail="El departamento indicado no existe")
        user = user_repository.create(email, hash_password(payload.password), role_id, payload.department_id, payload.account_type)
        note(request, resource_id=user.id, details={"role_id": role_id, "department_id": payload.department_id, "account_type": payload.account_type})
        profile_repository.create(user.id, payload.name, payload.phone, payload.address)
        return RegisterResponse(id=user.id)

    @router.get("", response_model=list[UserListItem], dependencies=[Depends(require_access(Action.ADMINISTER))])
    def list_users() -> list[UserListItem]:
        from app.main import user_repository

        return [UserListItem.model_validate(user) for user in user_repository.list()]

    @router.get("/{user_id}", response_model=UserResponse, dependencies=[Depends(_is_self_or(Action.ADMINISTER))])
    def get_user(user_id: int) -> UserResponse:
        from app.main import user_repository

        user = user_repository.get(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        return UserResponse.model_validate(user)

    @router.put("/{user_id}", response_model=UserResponse)
    def update_user(user_id: int, payload: UserUpdate, request: Request, current_user=Depends(_is_self_or(Action.ADMINISTER))) -> UserResponse:
        from app.main import user_repository

        if payload.is_active is not None:
            authorize(current_user, Action.ADMINISTER)  # activar/desactivar cuentas es administración, aunque sea la propia
        if payload.email is not None:
            existing = user_repository.get_by_email(str(payload.email).lower())
            if existing is not None and existing.id != user_id:
                raise HTTPException(status_code=409, detail="El email ya está registrado")
            payload.email = str(payload.email).lower()
        user = user_repository.update(user_id, payload)
        if user is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        note(request, details={"changed": sorted(payload.model_dump(exclude_none=True))})
        return UserResponse.model_validate(user)

    @router.patch("/{user_id}/assignment", response_model=UserResponse, dependencies=[Depends(require_access(Action.ADMINISTER))])
    def assign_user(user_id: int, payload: AssignmentUpdate, request: Request) -> UserResponse:
        """Cambia el rol y/o el departamento de un usuario DE FORMA INDEPENDIENTE: lo que no se envía queda intacto."""
        from app.main import access_catalog, user_repository

        target = user_repository.get(user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        if payload.role_id is not None:
            new_role = access_catalog.get_role(payload.role_id)
            if new_role is None:
                raise HTTPException(status_code=422, detail="El rol indicado no existe")
            admin_role = access_catalog.get_role_by_code("admin")
            if admin_role and target.role_id == admin_role["id"] and payload.role_id != admin_role["id"] \
                    and user_repository.count_active_with_role(admin_role["id"], excluding=user_id) == 0:
                raise HTTPException(status_code=409, detail="No se puede degradar al último Admin activo")
        if payload.department_id is not None and access_catalog.get_department(payload.department_id) is None:
            raise HTTPException(status_code=422, detail="El departamento indicado no existe")
        user = user_repository.assign(user_id, role_id=payload.role_id, department_id=payload.department_id)
        # Cambio de permisos: queda el ANTES y el DESPUÉS (rol y departamento por separado).
        note(request, details={"role": {"from": target.role, "to": user.role}, "department": {"from": target.department, "to": user.department},
                               "target_email": str(target.email)})
        return UserResponse.model_validate(user)

    @router.delete("/{user_id}", status_code=204, response_model=None, dependencies=[Depends(require_access(Action.DELETE))])
    def delete_user(user_id: int) -> None:
        from app.main import access_catalog, federated_repository, profile_repository, user_repository

        target = user_repository.get(user_id)
        admin_role = access_catalog.get_role_by_code("admin")
        if target and admin_role and target.role_id == admin_role["id"] and target.is_active \
                and user_repository.count_active_with_role(admin_role["id"], excluding=user_id) == 0:
            raise HTTPException(status_code=409, detail="No se puede eliminar al último Admin activo")
        if not user_repository.delete(user_id):
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        profile_repository.delete_by_user_id(user_id)
        federated_repository.delete_for_user(user_id)  # un vínculo huérfano permitiría reutilizar esa identidad de Google

    return router
