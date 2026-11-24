from __future__ import annotations

from jose import JWTError

from services.agent.chat.router import ChatUser

from .security import decode_access_token


def authenticate_ws_token(token: str) -> ChatUser | None:
    """Valida el MISMO JWT que `get_current_user` (firma, caducidad y usuario activo). `None` si no es válido."""
    from app.main import user_repository

    try:
        user_id = decode_access_token(token)
    except (JWTError, ValueError, TypeError):
        return None
    user = user_repository.get(user_id)
    if user is None or not user.is_active:
        return None
    return ChatUser(user_id=str(user.id), is_admin="administer" in user.capabilities)  # capacidad, no nombre de rol
