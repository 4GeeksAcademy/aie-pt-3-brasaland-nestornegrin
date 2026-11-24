"""Persistencia de roles y departamentos (entidades propias, en TinyDB) y de los reportes internos."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from tinydb import Query, TinyDB

from .models import DEPARTMENTS_SEED, KNOWN_CAPABILITIES, ROLES_SEED


class CatalogError(ValueError):
    """Violación de una regla del catálogo (código duplicado, jerarquía rota…). La ruta la traduce a 409/422."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


class AccessCatalog:
    """Roles y departamentos. Los ids son los doc_id de TinyDB (estables; nunca se borran filas)."""

    def __init__(self, path: Path) -> None:
        self._database = TinyDB(path, indent=2)
        self._roles = self._database.table("roles")
        self._departments = self._database.table("departments")
        self._lock = RLock()
        self._seed()

    def _seed(self) -> None:
        with self._lock:
            if len(self._roles) == 0:
                for role in ROLES_SEED:  # orden = rango → ids 1, 2, 3
                    self._roles.insert(dict(role))
            if len(self._departments) == 0:
                for department in DEPARTMENTS_SEED:
                    self._departments.insert(dict(department))

    # ------------------------------------------------------------------ roles
    @staticmethod
    def _with_id(row: Any) -> dict:
        return {**row, "id": row.doc_id}

    def list_roles(self) -> list[dict]:
        with self._lock:
            return sorted((self._with_id(r) for r in self._roles.all()), key=lambda r: r["rank"])

    def get_role(self, role_id: int) -> dict | None:
        with self._lock:
            row = self._roles.get(doc_id=role_id)
        return self._with_id(row) if row else None

    def get_role_by_code(self, code: str) -> dict | None:
        with self._lock:
            row = self._roles.get(Query().code == code)
        return self._with_id(row) if row else None

    def create_role(self, values: dict) -> dict:
        with self._lock:
            unknown = set(values["capabilities"]) - KNOWN_CAPABILITIES
            if unknown:
                raise CatalogError(f"Capacidades desconocidas: {', '.join(sorted(unknown))}")
            if self.get_role_by_code(values["code"]):
                raise CatalogError("Ya existe un rol con ese código", 409)
            roles = self.list_roles()
            if any(r["rank"] == values["rank"] for r in roles):
                raise CatalogError("Ya existe un rol con ese rango: la jerarquía es estricta", 409)
            capabilities = set(values["capabilities"])
            # Jerarquía verificable: un rol de rango mayor incluye SIEMPRE las capacidades de los de rango menor.
            for other in roles:
                if other["rank"] < values["rank"] and not set(other["capabilities"]) <= capabilities:
                    raise CatalogError(f"Rompe la jerarquía: debe incluir las capacidades del rol «{other['code']}» (rango inferior)")
                if other["rank"] > values["rank"] and not capabilities <= set(other["capabilities"]):
                    raise CatalogError(f"Rompe la jerarquía: no puede superar las capacidades del rol «{other['code']}» (rango superior)")
            doc_id = self._roles.insert({**values, "capabilities": sorted(capabilities)})
            return self.get_role(doc_id)  # type: ignore[return-value]

    def update_role(self, role_id: int, changes: dict) -> dict | None:
        with self._lock:
            if self._roles.get(doc_id=role_id) is None:
                return None
            if changes:
                self._roles.update(changes, doc_ids=[role_id])
            return self.get_role(role_id)

    def minimum_role_for(self, capability: str) -> dict | None:
        """Rol de menor rango que tiene la capacidad (para mensajes 403 explícitos)."""
        for role in self.list_roles():
            if capability in role["capabilities"]:
                return role
        return None

    # ------------------------------------------------------------------ departamentos
    def list_departments(self) -> list[dict]:
        with self._lock:
            return [self._with_id(r) for r in self._departments.all()]

    def get_department(self, department_id: int) -> dict | None:
        with self._lock:
            row = self._departments.get(doc_id=department_id)
        return self._with_id(row) if row else None

    def get_department_by_code(self, code: str) -> dict | None:
        with self._lock:
            row = self._departments.get(Query().code == code)
        return self._with_id(row) if row else None

    def create_department(self, values: dict) -> dict:
        with self._lock:
            if self.get_department_by_code(values["code"]):
                raise CatalogError("Ya existe un departamento con ese código", 409)
            doc_id = self._departments.insert(dict(values))
            return self.get_department(doc_id)  # type: ignore[return-value]

    def update_department(self, department_id: int, changes: dict) -> dict | None:
        with self._lock:
            if self._departments.get(doc_id=department_id) is None:
                return None
            if changes:
                self._departments.update(changes, doc_ids=[department_id])
            return self.get_department(department_id)


class InternalReportRepository:
    """Colección canónica con alcance departamental (`/internal-reports`)."""

    def __init__(self, path: Path) -> None:
        self._database = TinyDB(path, indent=2)
        self._lock = RLock()

    def create(self, department_id: int, title: str, body: str, created_by: int) -> dict:
        row = {"id": str(uuid.uuid4()), "department_id": department_id, "title": title, "body": body, "created_by": created_by,
               "created_at": datetime.now(timezone.utc).isoformat(), "approved_by": None, "approved_at": None}
        with self._lock:
            self._database.insert(row)
        return row

    def get(self, report_id: str) -> dict | None:
        with self._lock:
            row = self._database.get(Query().id == report_id)
        return dict(row) if row else None

    def list(self, department_id: int | None = None) -> list[dict]:
        with self._lock:
            rows = self._database.all() if department_id is None else self._database.search(Query().department_id == department_id)
        return sorted((dict(r) for r in rows), key=lambda r: r["created_at"])

    def update(self, report_id: str, changes: dict) -> dict | None:
        with self._lock:
            if self._database.get(Query().id == report_id) is None:
                return None
            if changes:
                self._database.update(changes, Query().id == report_id)
        return self.get(report_id)

    def delete(self, report_id: str) -> bool:
        with self._lock:
            return bool(self._database.remove(Query().id == report_id))

    def truncate(self) -> None:
        with self._lock:
            self._database.truncate()
