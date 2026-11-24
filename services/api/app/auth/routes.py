import hashlib
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status

from app import security as limits
from .dependencies import get_current_user
from .email import send_password_reset_email
from .models import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    MessageResponse,
    PasswordChangedResponse,
    ProfilePublic,
    ResetPasswordRequest,
    TokenResponse,
)
from .security import (
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    generate_password_reset_token,
    hash_password,
    hash_password_reset_token,
    verify_password,
)

logger = logging.getLogger(__name__)

# Mensaje único para /forgot-password: se devuelve exista o no el email, para
# no permitir que alguien enumere qué direcciones están registradas.
FORGOT_PASSWORD_MESSAGE = "Si esa dirección está en nuestro sistema, recibirás un enlace en breve."


_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("contraseña-ficticia-para-igualar-tiempos")
    return _DUMMY_HASH


def create_router() -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])

    @router.post("/login", response_model=TokenResponse)
    def login(credentials: LoginRequest, request: Request) -> TokenResponse:
        from app.main import user_repository

        # A07: límite de intentos fallidos por cuenta y por IP (antes de tocar la contraseña).
        account_key, ip_key = credentials.login_email, limits.client_ip(request)
        pair_key = f"{account_key}|{ip_key}"
        limits.login_by_account_ip.check(pair_key)  # V4: bloquea al que falla, no a la víctima
        limits.login_by_account.check(account_key)
        limits.login_by_ip.check(ip_key)
        user = user_repository.get_by_email(credentials.login_email)
        # Se verifica un hash también cuando el usuario no existe: mismo coste, no se delata qué emails están registrados.
        hashed = user.hashed_password if user is not None else _dummy_hash()
        if not verify_password(credentials.password, hashed) or user is None:
            limits.login_by_account_ip.record(pair_key)
            limits.login_by_account.record(account_key)
            limits.login_by_ip.record(ip_key)
            # A09: los fallos de login quedan en el log (cuenta como huella, nunca la contraseña) para detectar fuerza bruta.
            logger.warning("login_failed account=%s ip=%s", hashlib.sha256(account_key.encode()).hexdigest()[:12], ip_key)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email o contraseña incorrectos",
                headers={"WWW-Authenticate": "Bearer"},
            )
        limits.login_by_account_ip.clear(pair_key)
        limits.login_by_account.clear(account_key)
        return TokenResponse(access_token=create_access_token(user.id, user.hashed_password))

    @router.get("/me", response_model=MeResponse)
    def current_user(user=Depends(get_current_user)) -> MeResponse:
        from app.main import profile_repository

        profile = profile_repository.get_by_user_id(user.id)
        return MeResponse(
            email=user.email,
            role=user.role,
            profile=ProfilePublic.model_validate(profile) if profile else None,
        )

    @router.post("/forgot-password", response_model=MessageResponse)
    def forgot_password(payload: ForgotPasswordRequest, request: Request) -> MessageResponse:
        from app.main import password_reset_repository, user_repository

        # A04/A07: cada solicitud cuenta (evita inundar buzones ajenos y agotar el límite del proveedor de email).
        limits.forgot_by_ip.check(limits.client_ip(request))
        limits.forgot_by_ip.record(limits.client_ip(request))

        user = user_repository.get_by_email(str(payload.email).lower())
        if user is not None:
            raw_token = generate_password_reset_token()
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=PASSWORD_RESET_TOKEN_EXPIRE_MINUTES)
            password_reset_repository.create(user.id, hash_password_reset_token(raw_token), expires_at)
            try:
                send_password_reset_email(user.email, raw_token)
            except Exception:
                # Llamada a un servicio externo (Resend): un fallo aquí (red,
                # clave inválida, límite de envíos) nunca debe filtrar si el
                # email existe ni convertirse en un 500 -- se registra en el
                # log del servidor para que el equipo lo pueda diagnosticar,
                # y la respuesta al cliente sigue siendo la misma de siempre.
                logger.exception("No se pudo enviar el email de restablecimiento de contraseña")
        # Misma respuesta exista o no el usuario: ver FORGOT_PASSWORD_MESSAGE.
        return MessageResponse(message=FORGOT_PASSWORD_MESSAGE)

    @router.post("/reset-password", response_model=MessageResponse)
    def reset_password(payload: ResetPasswordRequest, request: Request) -> MessageResponse:
        from app.main import password_reset_repository, user_repository

        # V5b: canjear tokens al azar no tenía límite; cada intento cuenta.
        limits.reset_by_ip.check(limits.client_ip(request))
        limits.reset_by_ip.record(limits.client_ip(request))

        record = password_reset_repository.get_by_token_hash(hash_password_reset_token(payload.token))
        if record is None or record.used or record.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="El enlace de restablecimiento es inválido o ha expirado")
        user_repository.update_password(record.user_id, hash_password(payload.new_password))
        password_reset_repository.mark_used(record.id)
        return MessageResponse(message="Tu contraseña se actualizó correctamente")

    @router.post("/change-password", response_model=PasswordChangedResponse)
    def change_password(payload: ChangePasswordRequest, current_user=Depends(get_current_user)) -> PasswordChangedResponse:
        from app.main import user_repository

        # V5a: con un token robado se podía adivinar la contraseña actual sin límite.
        key = f"user:{current_user.id}"
        limits.sensitive_by_user.check(key)
        if not verify_password(payload.current_password, current_user.hashed_password):
            limits.sensitive_by_user.record(key)
            raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta")
        new_hash = hash_password(payload.new_password)
        user_repository.update_password(current_user.id, new_hash)
        # V1: los tokens anteriores (incluido uno robado) dejan de valer; la sesión actual recibe uno nuevo.
        return PasswordChangedResponse(message="Tu contraseña se actualizó correctamente",
                                       access_token=create_access_token(current_user.id, new_hash))

    return router
