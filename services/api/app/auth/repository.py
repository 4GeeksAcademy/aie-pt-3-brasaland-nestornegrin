from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from tinydb import Query, TinyDB

from app.access.catalog import AccessCatalog

from .models import PasswordResetRecord, ProfileRecord, ProfileUpdate, UserRecord, UserUpdate


class UserRepository:
    """Usuarios en TinyDB. Guarda `role_id` y `department_id` (claves foráneas independientes al catálogo de acceso)."""

    _LEGACY_ROLE_CODES = {"user": "employee", "manager": "supervisor", "admin": "admin"}  # roles planos anteriores

    def __init__(self, path: Path, catalog: AccessCatalog) -> None:
        self._database = TinyDB(path, indent=2)
        self._lock = Lock()
        self._catalog = catalog
        self._migrate_legacy_roles()

    def _migrate_legacy_roles(self) -> None:
        """Cuentas creadas antes de Roles y Permisos tenían `role` ('user'|'manager'|'admin') y ningún departamento.
        Se convierten una sola vez a `role_id`; el departamento queda vacío hasta que un Admin lo asigne."""
        with self._lock:
            for row in self._database.all():
                if "role_id" in row:
                    continue
                code = self._LEGACY_ROLE_CODES.get(row.get("role", "user"), "employee")
                role = self._catalog.get_role_by_code(code)
                self._database.update({"role_id": role["id"], "department_id": None}, doc_ids=[row.doc_id])
                self._database.update(lambda doc: doc.pop("role", None), doc_ids=[row.doc_id])

    def _record(self, row, user_id: int) -> UserRecord:
        role = self._catalog.get_role(row["role_id"]) or {"code": "", "rank": 0, "capabilities": []}
        department = self._catalog.get_department(row["department_id"]) if row.get("department_id") else None
        return UserRecord.model_validate({
            **row,
            "id": user_id,
            "role": role["code"],
            "rank": role["rank"],
            "capabilities": role["capabilities"],
            "department": department["code"] if department else None,
        })

    def create(self, email: str, hashed_password: str, role_id: int | None = None, department_id: int | None = None) -> UserRecord:
        now = datetime.now(timezone.utc)
        if role_id is None:
            role_id = self._catalog.list_roles()[0]["id"]  # rol de menor rango
        with self._lock:
            document_id = self._database.insert({
                "email": email,
                "hashed_password": hashed_password,
                "is_active": True,
                "role_id": role_id,
                "department_id": department_id,
                "created_at": now.isoformat(),
            })
            row = self._database.get(doc_id=document_id)
        return self._record(row, document_id)

    def get(self, user_id: int) -> UserRecord | None:
        with self._lock:
            row = self._database.get(doc_id=user_id)
        return self._record(row, row.doc_id) if row else None

    def get_by_email(self, email: str) -> UserRecord | None:
        with self._lock:
            row = self._database.get(Query().email == email)
        return self._record(row, row.doc_id) if row else None

    def list(self) -> list[UserRecord]:
        with self._lock:
            rows = self._database.all()
        return [self._record(row, row.doc_id) for row in rows]

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
        return self._record(row, user_id)

    def assign(self, user_id: int, *, role_id: int | None = None, department_id: int | None = None) -> UserRecord | None:
        """Cambia SOLO lo que se pasa: rol y departamento son ejes independientes (cambiar uno deja el otro intacto)."""
        values = {key: value for key, value in (("role_id", role_id), ("department_id", department_id)) if value is not None}
        with self._lock:
            row = self._database.get(doc_id=user_id)
            if row is None:
                return None
            if values:
                self._database.update(values, doc_ids=[user_id])
                row.update(values)
        return self._record(row, user_id)

    def count_active_with_role(self, role_id: int, excluding: int | None = None) -> int:
        with self._lock:
            rows = self._database.all()
        return sum(1 for r in rows if r.get("role_id") == role_id and r.get("is_active", True) and r.doc_id != excluding)

    def update_password(self, user_id: int, hashed_password: str) -> UserRecord | None:
        with self._lock:
            row = self._database.get(doc_id=user_id)
            if row is None:
                return None
            self._database.update({"hashed_password": hashed_password}, doc_ids=[user_id])
            row.update({"hashed_password": hashed_password})
        return self._record(row, user_id)

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
