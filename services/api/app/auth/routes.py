import hashlib
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status

from app import security as limits
from app.audit.recorder import note
from .dependencies import get_current_user
from services.async_tasks import config, dlq
from services.async_tasks.enqueue import enqueue_password_reset_email
from .models import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    MessageResponse,
    PasswordChangedResponse,
    ProfilePublic,
    RegisterResponse,
    ResetPasswordRequest,
    TokenResponse,
    UserCreate,
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
        note(request, label=credentials.login_email)
        user = user_repository.get_by_email(credentials.login_email)
        # Se verifica un hash también cuando el usuario no existe: mismo coste, no se delata qué emails están registrados.
        # (una cuenta sin contraseña —solo acceso federado— tampoco puede entrar por aquí.)
        hashed = user.hashed_password if user is not None and user.hashed_password else _dummy_hash()
        if not verify_password(credentials.password, hashed) or user is None or not user.hashed_password:
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
        note(request, user=user, resource_id=user.id, details={"method": "password"})
        return TokenResponse(access_token=create_access_token(user.id, user.hashed_password))

    @router.post("/register", response_model=RegisterResponse, status_code=201)
    def register(payload: UserCreate, request: Request) -> RegisterResponse:
        """Registro público de autoservicio (A04: tope por IP). La cuenta nace con el rol de menor rango (Empleado) y SIN
        departamento: no puede ver datos departamentales hasta que un Admin se lo asigne (PATCH /users/{id}/assignment)."""
        from app.main import profile_repository, user_repository

        limits.register_by_ip.check(limits.client_ip(request))
        limits.register_by_ip.record(limits.client_ip(request))

        email = str(payload.email).lower()
        if user_repository.get_by_email(email):
            raise HTTPException(status_code=409, detail="El email ya está registrado")
        user = user_repository.create(email, hash_password(payload.password))
        note(request, label=email, resource_id=user.id)
        profile_repository.create(user.id, payload.name, payload.phone, payload.address)
        return RegisterResponse(id=user.id)

    @router.get("/me", response_model=MeResponse)
    def current_user(user=Depends(get_current_user)) -> MeResponse:
        from app.main import access_catalog, profile_repository

        profile = profile_repository.get_by_user_id(user.id)
        role = access_catalog.get_role(user.role_id)
        department = access_catalog.get_department(user.department_id) if user.department_id else None
        return MeResponse(
            email=user.email,
            role_id=user.role_id,
            role=user.role,
            role_label=role["label"] if role else user.role,
            rank=user.rank,
            department_id=user.department_id,
            department=user.department,
            department_label=department["label"] if department else None,
            capabilities=user.capabilities,
            profile=ProfilePublic.model_validate(profile) if profile else None,
        )

    @router.post("/forgot-password", response_model=MessageResponse)
    def forgot_password(payload: ForgotPasswordRequest, request: Request) -> MessageResponse:
        from app.main import password_reset_repository, user_repository

        # A04/A07: cada solicitud cuenta (evita inundar buzones ajenos y agotar el límite del proveedor de email).
        limits.forgot_by_ip.check(limits.client_ip(request))
        limits.forgot_by_ip.record(limits.client_ip(request))

        note(request, label=str(payload.email).lower())  # solo el correo indicado: la respuesta no revela si existe
        user = user_repository.get_by_email(str(payload.email).lower())
        if user is not None:
            raw_token = generate_password_reset_token()
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=PASSWORD_RESET_TOKEN_EXPIRE_MINUTES)
            # El envío (servicio externo: Resend) ya NO ocurre dentro de la petición: se encola y lo procesa un worker con
            # reintentos y backoff. La clave de idempotencia hace que encolar dos veces la misma solicitud no envíe dos emails.
            record = password_reset_repository.create(user.id, hash_password_reset_token(raw_token), expires_at)
            idempotency_key = f"password-reset:{record.id}"
            try:
                enqueue_password_reset_email(user.email, raw_token, idempotency_key)
            except Exception as error:  # noqa: BLE001
                # La COLA está caída: el email no se ha perdido en silencio, queda en la dead-letter queue y en el log (error).
                # La respuesta sigue siendo idéntica exista o no el usuario (no se filtra nada).
                logger.error("No se pudo encolar el email de restablecimiento (%s)", idempotency_key, exc_info=True)
                dlq.record_dead_letter(task_id=idempotency_key, task_name=config.SEND_PASSWORD_RESET_TASK, attempt=0,
                                       error_message=f"No se pudo encolar: {type(error).__name__}")
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
        note(request, user=user_repository.get(record.user_id), resource_id=record.user_id)
        return MessageResponse(message="Tu contraseña se actualizó correctamente")

    @router.post("/change-password", response_model=PasswordChangedResponse)
    def change_password(payload: ChangePasswordRequest, request: Request, current_user=Depends(get_current_user)) -> PasswordChangedResponse:
        from app.main import user_repository

        if not current_user.hashed_password:
            raise HTTPException(status_code=400, detail="Tu cuenta no tiene contraseña. Usa «¿Olvidaste tu contraseña?» para crear una.")
        # V5a: con un token robado se podía adivinar la contraseña actual sin límite.
        key = f"user:{current_user.id}"
        limits.sensitive_by_user.check(key)
        if not verify_password(payload.current_password, current_user.hashed_password):
            limits.sensitive_by_user.record(key)
            raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta")
        new_hash = hash_password(payload.new_password)
        user_repository.update_password(current_user.id, new_hash)
        note(request, resource_id=current_user.id)
        # V1: los tokens anteriores (incluido uno robado) dejan de valer; la sesión actual recibe uno nuevo.
        return PasswordChangedResponse(message="Tu contraseña se actualizó correctamente",
                                       access_token=create_access_token(current_user.id, new_hash))

    return router
