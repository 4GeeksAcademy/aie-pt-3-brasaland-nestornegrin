import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from jose import ExpiredSignatureError, JWTError, jwt
from passlib.hash import bcrypt

from .models import MAX_PASSWORD_LENGTH

load_dotenv()

MIN_SECRET_LENGTH = 32
_PLACEHOLDERS = ("changeme", "cambia-esto", "cambia_esto", "your-secret", "tu-secreto", "example", "placeholder")


def ensure_strong_secret(secret: str | None) -> str:
    """A02: el secreto que firma los JWT debe ser largo, variado y no un valor de ejemplo (cualquiera podría falsificar sesiones)."""
    value = (secret or "").strip()
    if not value:
        raise RuntimeError("JWT_SECRET_KEY debe estar configurada en el entorno")
    if len(value) < MIN_SECRET_LENGTH or len(set(value)) < 8 or any(word in value.lower() for word in _PLACEHOLDERS):
        raise RuntimeError(f"JWT_SECRET_KEY es débil: usa al menos {MIN_SECRET_LENGTH} caracteres aleatorios "
                           "(p. ej. `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`).")
    return value


_raw_secret = os.getenv("JWT_SECRET_KEY")
if not _raw_secret:
    raise RuntimeError("JWT_SECRET_KEY debe estar configurada en el entorno")
try:
    JWT_SECRET_KEY = ensure_strong_secret(_raw_secret)
except RuntimeError as weak_secret:
    if os.getenv("APP_ENV", "development").lower() == "production":
        raise  # en producción un secreto débil impide arrancar
    logging.getLogger(__name__).warning("%s (solo se tolera fuera de producción)", weak_secret)
    JWT_SECRET_KEY = _raw_secret
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
if JWT_ALGORITHM not in {"HS256", "HS384", "HS512"}:  # A02: nunca `none` ni algoritmos asimétricos con un secreto compartido
    raise RuntimeError(f"JWT_ALGORITHM no admitido: {JWT_ALGORITHM!r} (solo HS256/HS384/HS512).")
def _split_keys(raw: str | None) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


# Rotación sin cortes (docs/security/secret-rotation.md): se firma SIEMPRE con la clave nueva, pero mientras dura la
# transición se siguen aceptando los tokens firmados con las claves anteriores (JWT_SECRET_KEY_PREVIOUS="vieja1,vieja2").
JWT_PREVIOUS_KEYS = _split_keys(os.getenv("JWT_SECRET_KEY_PREVIOUS"))
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES = int(os.getenv("PASSWORD_RESET_TOKEN_EXPIRE_MINUTES", "30"))


def hash_password(password: str) -> str:
    return bcrypt.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    if len(password) > MAX_PASSWORD_LENGTH:  # nunca se hashea algo que ninguna cuenta puede tener (y no hay 500)
        return False
    try:
        return bcrypt.verify(password, hashed_password)
    except ValueError:
        return False


def password_fingerprint(hashed_password: str) -> str:
    """Huella de la contraseña vigente. Va dentro del JWT: al cambiar o restablecer la contraseña (hash nuevo) todos los
    tokens emitidos antes dejan de valer, sin guardar listas de tokens revocados en el servidor (V1)."""
    return hashlib.sha256(hashed_password.encode("utf-8")).hexdigest()[:16]


def create_access_token(user_id: int, hashed_password: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    claims: dict = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)}
    if hashed_password is not None:
        claims["pwf"] = password_fingerprint(hashed_password)
    return jwt.encode(claims, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_claims(token: str) -> dict:
    """Verifica firma y caducidad con la clave vigente y, si falla la firma, con las anteriores (rotación)."""
    last_error: JWTError | None = None
    for key in [JWT_SECRET_KEY, *JWT_PREVIOUS_KEYS]:
        try:
            return jwt.decode(token, key, algorithms=[JWT_ALGORITHM])
        except ExpiredSignatureError:
            raise
        except JWTError as error:
            last_error = error
    raise last_error or JWTError("Token inválido")


def decode_access_token(token: str) -> int:
    subject = decode_access_claims(token).get("sub")
    if not isinstance(subject, str) or not subject.isdigit():
        raise JWTError("Token sin identificador de usuario válido")
    return int(subject)


def token_matches_password(token: str, hashed_password: str) -> bool:
    """El token solo vale mientras la contraseña no haya cambiado desde que se emitió."""
    claim = decode_access_claims(token).get("pwf")
    return isinstance(claim, str) and secrets.compare_digest(claim, password_fingerprint(hashed_password))


def generate_password_reset_token() -> str:
    """Genera un token aleatorio de alta entropía (no un JWT).

    Se guarda hasheado en la base de datos junto con su expiración y estado
    de uso, porque un JWT solo con `exp` no puede invalidarse tras un único
    uso: haría falta persistir estado en el servidor de todas formas.
    """
    return secrets.token_urlsafe(32)


def hash_password_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
