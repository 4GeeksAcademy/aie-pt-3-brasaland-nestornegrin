from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import get_current_user
from app.auth.models import ProfileResponse, ProfileUpdate


def create_router() -> APIRouter:
    router = APIRouter(prefix="/profiles", tags=["profiles"])

    @router.get("/me", response_model=ProfileResponse)
    def get_my_profile(current_user=Depends(get_current_user)) -> ProfileResponse:
        from app.main import profile_repository

        profile = profile_repository.get_by_user_id(current_user.id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Perfil no encontrado")
        return ProfileResponse.model_validate(profile)

    @router.put("/me", response_model=ProfileResponse)
    def update_my_profile(payload: ProfileUpdate, current_user=Depends(get_current_user)) -> ProfileResponse:
        from app.main import profile_repository

        profile = profile_repository.update_by_user_id(current_user.id, payload)
        if profile is None:
            raise HTTPException(status_code=404, detail="Perfil no encontrado")
        return ProfileResponse.model_validate(profile)

    return router
