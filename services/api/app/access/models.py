"""Control de acceso (Roles y Permisos) — entidades y esquemas.

Dos ejes INDEPENDIENTES (ver docs/security/roles-permissions.md):
  · ROL          → ¿qué puede hacer esta persona?     (capacidades, jerarquía por rango)
  · DEPARTAMENTO → ¿qué información le compete?       (alcance de datos; no otorga acciones)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Action(str, Enum):
    """Capacidades atómicas del sistema. Un rol es un conjunto de ellas."""

    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    APPROVE = "approve"
    DELETE = "delete"
    ADMINISTER = "administer"  # usuarios, roles y departamentos


# Capacidad especial (no es una acción): ver/operar datos de CUALQUIER departamento. Es un privilegio de ROL (Admin).
CROSS_DEPARTMENT = "cross_department"
KNOWN_CAPABILITIES = frozenset({action.value for action in Action} | {CROSS_DEPARTMENT})


class UserRole(str, Enum):
    """Códigos de los roles sembrados (BRIEFING). Los roles viven en la base de datos: pueden existir más."""

    EMPLOYEE = "employee"
    SUPERVISOR = "supervisor"
    ADMIN = "admin"


class DepartmentCode(str, Enum):
    RESTAURANT_OPERATIONS = "restaurant_operations"
    PROCUREMENT = "procurement"
    MARKETING = "marketing"
    PEOPLE_CULTURE = "people_culture"
    TRAINING_QUALITY = "training_quality"
    TECHNOLOGY = "technology"


# --------------------------------------------------------------------------- semilla EXACTA del BRIEFING
ROLES_SEED = [
    {"code": "employee", "name": "Employee", "label": "Empleado", "rank": 1,
     "description": "Crea y lee registros de su departamento. No aprueba, no elimina, no administra.",
     "capabilities": ["read", "create"]},
    {"code": "supervisor", "name": "Supervisor", "label": "Supervisor", "rank": 2,
     "description": "Todo lo de Empleado, más actualizar y aprobar registros de su departamento.",
     "capabilities": ["read", "create", "update", "approve"]},
    {"code": "admin", "name": "Admin", "label": "Admin", "rank": 3,
     "description": "Todo lo de Supervisor, más eliminar y administrar usuarios, roles y departamentos. Ve todos los departamentos.",
     "capabilities": ["read", "create", "update", "approve", "delete", "administer", CROSS_DEPARTMENT]},
]

DEPARTMENTS_SEED = [
    {"code": "restaurant_operations", "name": "Restaurant Operations", "label": "Operaciones de restaurante",
     "responsible": "Felipe Guerrero", "description": "Incidentes de local, reportes de turno, notas operativas de cocina/sala"},
    {"code": "procurement", "name": "Procurement and Suppliers", "label": "Compras y proveedores",
     "responsible": "Lucía Fernández", "description": "Proveedores, tarifas, notas de compra"},
    {"code": "marketing", "name": "Marketing and Digital Experience", "label": "Marketing y experiencia digital",
     "responsible": "Camila Ospina", "description": "Campañas, loyalty, notas de cara al cliente"},
    {"code": "people_culture", "name": "People and Culture", "label": "Personas y cultura",
     "responsible": "Ashley Turner", "description": "Notas de plantilla, turnos, onboarding"},
    {"code": "training_quality", "name": "Training and Quality Standards", "label": "Formación y estándares de calidad",
     "responsible": "Jake Morrison", "description": "Recetas, materiales de formación, notas de calidad"},
    {"code": "technology", "name": "Technology", "label": "Tecnología",
     "responsible": "Nicolás Park", "description": "Notas de configuración de plataforma"},
]

# --------------------------------------------------------------------------- esquemas de la API
_CODE_PATTERN = r"^[a-z][a-z0-9_]{1,39}$"


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    label: str
    rank: int
    description: str
    capabilities: list[str]


class RoleCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: str = Field(pattern=_CODE_PATTERN)
    name: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=80)
    rank: int = Field(ge=1, le=99)
    description: str = Field(default="", max_length=300)
    capabilities: list[str] = Field(min_length=1)


class RoleUpdate(BaseModel):
    """Solo metadatos: el rango y las capacidades de un rol existente no se editan (la jerarquía es estable)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    label: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=300)


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    label: str
    responsible: str
    description: str


class DepartmentCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: str = Field(pattern=_CODE_PATTERN)
    name: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=80)
    responsible: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=300)


class DepartmentUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    label: str | None = Field(default=None, min_length=1, max_length=80)
    responsible: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=300)


class AssignmentUpdate(BaseModel):
    """PATCH /users/{id}/assignment. Solo cambia lo que viene en el cuerpo: rol y departamento son independientes."""

    model_config = ConfigDict(extra="forbid")

    role_id: int | None = Field(default=None, gt=0)
    department_id: int | None = Field(default=None, gt=0)


class InternalReportCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    department_id: int | None = Field(default=None, gt=0, description="Opcional: por defecto, el departamento del autor. Solo Admin puede elegir otro.")


class InternalReportUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=5000)


class InternalReportOut(BaseModel):
    id: str
    department_id: int
    department: str
    title: str
    body: str
    created_by: int
    created_at: datetime
    approved_by: int | None = None
    approved_at: datetime | None = None
