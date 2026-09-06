from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_user
from app.auth.models import UserCreate, UserResponse, UserRole, UserUpdate
from app.auth.security import hash_password


def create_router() -> APIRouter:
    router = APIRouter(prefix="/users", tags=["users"])

    @router.post("", response_model=UserResponse, status_code=201)
    def create_user(payload: UserCreate) -> UserResponse:
        from app.main import profile_repository, user_repository

        email = str(payload.email).lower()
        if user_repository.get_by_email(email):
            raise HTTPException(status_code=409, detail="El email ya está registrado")
        user = user_repository.create(email, hash_password(payload.password))
        profile_repository.create(user.id, payload.name, payload.phone, payload.address)
        return UserResponse.model_validate(user)

    @router.get("", response_model=list[UserResponse])
    def list_users(current_user=Depends(get_current_user)) -> list[UserResponse]:
        from app.main import user_repository

        if current_user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Solo un admin puede listar usuarios")
        return [UserResponse.model_validate(user) for user in user_repository.list()]

    @router.get("/{user_id}", response_model=UserResponse)
    def get_user(user_id: int, current_user=Depends(get_current_user)) -> UserResponse:
        from app.main import user_repository

        if current_user.id != user_id and current_user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="No puedes consultar este usuario")
        user = user_repository.get(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        return UserResponse.model_validate(user)

    @router.put("/{user_id}", response_model=UserResponse)
    def update_user(user_id: int, payload: UserUpdate, current_user=Depends(get_current_user)) -> UserResponse:
        from app.main import user_repository

        if current_user.id != user_id and current_user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="No puedes modificar este usuario")
        if payload.role is not None and current_user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Solo un admin puede cambiar roles")
        if payload.email is not None:
            existing = user_repository.get_by_email(str(payload.email).lower())
            if existing is not None and existing.id != user_id:
                raise HTTPException(status_code=409, detail="El email ya está registrado")
            payload.email = str(payload.email).lower()
        user = user_repository.update(user_id, payload)
        if user is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        return UserResponse.model_validate(user)

    @router.delete("/{user_id}", status_code=204)
    def delete_user(user_id: int, current_user=Depends(get_current_user)) -> None:
        from app.main import profile_repository, user_repository

        if current_user.id != user_id and current_user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="No puedes eliminar este usuario")
        if not user_repository.delete(user_id):
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        profile_repository.delete_by_user_id(user_id)

    return router
