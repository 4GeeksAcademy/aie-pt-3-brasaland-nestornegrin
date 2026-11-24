import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from jose import JWTError, jwt
from passlib.hash import bcrypt

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
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES = int(os.getenv("PASSWORD_RESET_TOKEN_EXPIRE_MINUTES", "30"))


def hash_password(password: str) -> str:
    return bcrypt.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.verify(password, hashed_password)


def create_access_token(user_id: int) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": str(user_id), "exp": expires_at}, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> int:
    payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.isdigit():
        raise JWTError("Token sin identificador de usuario válido")
    return int(subject)


def generate_password_reset_token() -> str:
    """Genera un token aleatorio de alta entropía (no un JWT).

    Se guarda hasheado en la base de datos junto con su expiración y estado
    de uso, porque un JWT solo con `exp` no puede invalidarse tras un único
    uso: haría falta persistir estado en el servidor de todas formas.
    """
    return secrets.token_urlsafe(32)


def hash_password_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
