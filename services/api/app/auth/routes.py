from fastapi import APIRouter, Depends, Form, HTTPException, status

from .dependencies import get_current_user
from .models import LoginRequest, MeResponse, ProfileResponse, TokenResponse, UserResponse
from .security import create_access_token, verify_password


def create_router() -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])

    @router.post("/login", response_model=TokenResponse)
    def login(credentials: LoginRequest) -> TokenResponse:
        from app.main import user_repository

        user = user_repository.get_by_email(credentials.login_email)
        if user is None or not verify_password(credentials.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email o contraseña incorrectos",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return TokenResponse(access_token=create_access_token(user.id))

    @router.get("/me", response_model=MeResponse)
    def current_user(user=Depends(get_current_user)) -> MeResponse:
        from app.main import profile_repository

        profile = profile_repository.get_by_user_id(user.id)
        return MeResponse(
            email=user.email,
            role=user.role,
            profile=ProfileResponse.model_validate(profile) if profile else None,
        )

    return router
