from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, status

from .dependencies import get_current_user
from .email import send_password_reset_email
from .models import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    MessageResponse,
    ProfileResponse,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
)
from .security import (
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    generate_password_reset_token,
    hash_password,
    hash_password_reset_token,
    verify_password,
)

# Mensaje único para /forgot-password: se devuelve exista o no el email, para
# no permitir que alguien enumere qué direcciones están registradas.
FORGOT_PASSWORD_MESSAGE = "Si esa dirección está en nuestro sistema, recibirás un enlace en breve."


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

    @router.post("/forgot-password", response_model=MessageResponse)
    def forgot_password(payload: ForgotPasswordRequest) -> MessageResponse:
        from app.main import password_reset_repository, user_repository

        user = user_repository.get_by_email(str(payload.email).lower())
        if user is not None:
            raw_token = generate_password_reset_token()
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=PASSWORD_RESET_TOKEN_EXPIRE_MINUTES)
            password_reset_repository.create(user.id, hash_password_reset_token(raw_token), expires_at)
            send_password_reset_email(user.email, raw_token)
        # Misma respuesta exista o no el usuario: ver FORGOT_PASSWORD_MESSAGE.
        return MessageResponse(message=FORGOT_PASSWORD_MESSAGE)

    @router.post("/reset-password", response_model=MessageResponse)
    def reset_password(payload: ResetPasswordRequest) -> MessageResponse:
        from app.main import password_reset_repository, user_repository

        record = password_reset_repository.get_by_token_hash(hash_password_reset_token(payload.token))
        if record is None or record.used or record.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="El enlace de restablecimiento es inválido o ha expirado")
        user_repository.update_password(record.user_id, hash_password(payload.new_password))
        password_reset_repository.mark_used(record.id)
        return MessageResponse(message="Tu contraseña se actualizó correctamente")

    @router.post("/change-password", response_model=MessageResponse)
    def change_password(payload: ChangePasswordRequest, current_user=Depends(get_current_user)) -> MessageResponse:
        from app.main import user_repository

        if not verify_password(payload.current_password, current_user.hashed_password):
            raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta")
        user_repository.update_password(current_user.id, hash_password(payload.new_password))
        return MessageResponse(message="Tu contraseña se actualizó correctamente")

    return router
