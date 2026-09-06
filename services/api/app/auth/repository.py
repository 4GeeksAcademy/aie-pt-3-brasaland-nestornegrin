from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from tinydb import Query, TinyDB

from .models import PasswordResetRecord, ProfileRecord, ProfileUpdate, UserRecord, UserUpdate


class UserRepository:
    def __init__(self, path: Path) -> None:
        self._database = TinyDB(path, indent=2)
        self._lock = Lock()

    def create(self, email: str, hashed_password: str) -> UserRecord:
        now = datetime.now(timezone.utc)
        with self._lock:
            document_id = self._database.insert({
                "email": email,
                "hashed_password": hashed_password,
                "is_active": True,
                "role": "user",
                "created_at": now.isoformat(),
            })
            row = self._database.get(doc_id=document_id)
        return UserRecord.model_validate({**row, "id": document_id})

    def get(self, user_id: int) -> UserRecord | None:
        with self._lock:
            row = self._database.get(doc_id=user_id)
        return UserRecord.model_validate({**row, "id": row.doc_id}) if row else None

    def get_by_email(self, email: str) -> UserRecord | None:
        with self._lock:
            row = self._database.get(Query().email == email)
        return UserRecord.model_validate({**row, "id": row.doc_id}) if row else None

    def list(self) -> list[UserRecord]:
        with self._lock:
            rows = self._database.all()
        return [UserRecord.model_validate({**row, "id": row.doc_id}) for row in rows]

    def update(self, user_id: int, changes: UserUpdate) -> UserRecord | None:
        values = changes.model_dump(exclude_none=True, mode="json")
        if not values:
            return self.get(user_id)
        with self._lock:
            row = self._database.get(doc_id=user_id)
            if row is None:
                return None
            self._database.update(values, doc_ids=[user_id])
            row.update(values)
        return UserRecord.model_validate({**row, "id": user_id})

    def update_password(self, user_id: int, hashed_password: str) -> UserRecord | None:
        with self._lock:
            row = self._database.get(doc_id=user_id)
            if row is None:
                return None
            self._database.update({"hashed_password": hashed_password}, doc_ids=[user_id])
            row.update({"hashed_password": hashed_password})
        return UserRecord.model_validate({**row, "id": user_id})

    def delete(self, user_id: int) -> bool:
        with self._lock:
            return bool(self._database.remove(doc_ids=[user_id]))


class ProfileRepository:
    def __init__(self, path: Path) -> None:
        self._database = TinyDB(path, indent=2)
        self._lock = Lock()

    def create(self, user_id: int, name: str = "", phone: str = "", address: str = "") -> ProfileRecord:
        with self._lock:
            document_id = self._database.insert({
                "user_id": user_id,
                "name": name,
                "phone": phone,
                "address": address,
            })
            row = self._database.get(doc_id=document_id)
        return ProfileRecord.model_validate({**row, "id": document_id})

    def get_by_user_id(self, user_id: int) -> ProfileRecord | None:
        with self._lock:
            row = self._database.get(Query().user_id == user_id)
        return ProfileRecord.model_validate({**row, "id": row.doc_id}) if row else None

    def update_by_user_id(self, user_id: int, changes: ProfileUpdate) -> ProfileRecord | None:
        values = changes.model_dump(exclude_none=True)
        with self._lock:
            row = self._database.get(Query().user_id == user_id)
            if row is None:
                return None
            if values:
                self._database.update(values, doc_ids=[row.doc_id])
                row.update(values)
        return ProfileRecord.model_validate({**row, "id": row.doc_id})

    def delete_by_user_id(self, user_id: int) -> bool:
        with self._lock:
            return bool(self._database.remove(Query().user_id == user_id))


class PasswordResetRepository:
    """Tokens de restablecimiento de contraseña.

    Solo se guarda el hash del token (nunca el valor enviado por email) junto
    con su expiración y si ya fue utilizado, para poder invalidarlo tras un
    único uso aunque el JWT/token en sí no soporte revocación nativa.
    """

    def __init__(self, path: Path) -> None:
        self._database = TinyDB(path, indent=2)
        self._lock = Lock()

    def create(self, user_id: int, token_hash: str, expires_at: datetime) -> PasswordResetRecord:
        now = datetime.now(timezone.utc)
        with self._lock:
            document_id = self._database.insert({
                "user_id": user_id,
                "token_hash": token_hash,
                "expires_at": expires_at.isoformat(),
                "used": False,
                "created_at": now.isoformat(),
            })
            row = self._database.get(doc_id=document_id)
        return PasswordResetRecord.model_validate({**row, "id": document_id})

    def get_by_token_hash(self, token_hash: str) -> PasswordResetRecord | None:
        with self._lock:
            row = self._database.get(Query().token_hash == token_hash)
        return PasswordResetRecord.model_validate({**row, "id": row.doc_id}) if row else None

    def mark_used(self, record_id: int) -> None:
        with self._lock:
            self._database.update({"used": True}, doc_ids=[record_id])
