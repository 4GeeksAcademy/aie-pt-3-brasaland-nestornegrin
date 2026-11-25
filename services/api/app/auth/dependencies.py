from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError

from .repository import UserRepository
from .security import decode_access_token, token_matches_password


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(request: Request, token: str = Depends(oauth2_scheme)):
    from app.main import user_repository

    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales inválidas",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = decode_access_token(token)
    except (JWTError, ValueError, TypeError):
        raise credentials_error
    user = user_repository.get(user_id)
    if user is None or not user.is_active:
        raise credentials_error
    try:
        if not token_matches_password(token, user.hashed_password or ""):  # V1: la contraseña cambió después de emitirse el token
            raise credentials_error
    except JWTError:
        raise credentials_error
    request.state.audit_user = user  # el audit log atribuye la acción a la identidad ya validada, nunca a lo que diga el cliente
    return user
