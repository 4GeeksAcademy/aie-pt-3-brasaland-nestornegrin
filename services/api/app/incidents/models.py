import sys
from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from packages.shared.incident_validation import ALLOWED_CATEGORIES  # noqa: E402

# Las categorías se derivan de packages/shared/incident_validation.py (la
# misma fuente que usa el CSV histórico) para no duplicar la lista de
# valores válidos en dos sitios distintos del monorepo.
IncidentCategory = Enum(  # type: ignore[misc]
    "IncidentCategory",
    {category.upper().replace(" ", "_"): category for category in ALLOWED_CATEGORIES},
    type=str,
)


class IncidentStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    DISCARDED = "discarded"


class IncidentOrigin(str, Enum):
    CUSTOMER = "customer"
    BRANCH = "branch"
    INTERNAL = "internal"


class Branch(str, Enum):
    """Sedes de Brasaland (CONTEXT.es.md, Hito 1) + 'central' para lo que no
    corresponde a una sede específica (equipo corporativo, incidencias sin
    ubicación conocida en el histórico, etc.)."""

    CENTRAL = "central"
    EL_POBLADO = "Brasaland El Poblado"
    LAURELES = "Brasaland Laureles"
    ENVIGADO = "Brasaland Envigado"
    SABANETA = "Brasaland Sabaneta"
    USAQUEN = "Brasaland Usaquén"
    CHAPINERO = "Brasaland Chapinero"
    ZONA_ROSA = "Brasaland Zona Rosa"
    GRANADA = "Brasaland Granada"
    CIUDAD_JARDIN = "Brasaland Ciudad Jardín"
    UNICENTRO = "Brasaland Unicentro"
    BRICKELL = "Brasaland Brickell"
    CORAL_GABLES = "Brasaland Coral Gables"
    DOWNTOWN = "Brasaland Downtown"
    INTERNATIONAL_DRIVE = "Brasaland International Drive"


# Transiciones de ciclo de vida permitidas. resolved/discarded son finales.
# Una transición al mismo estado se trata como no-op en las rutas, no como
# transición inválida.
ALLOWED_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.OPEN: {IncidentStatus.IN_PROGRESS, IncidentStatus.DISCARDED},
    IncidentStatus.IN_PROGRESS: {IncidentStatus.RESOLVED, IncidentStatus.DISCARDED},
    IncidentStatus.RESOLVED: set(),
    IncidentStatus.DISCARDED: set(),
}


class IncidentBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    category: IncidentCategory
    origin: IncidentOrigin
    branch: Branch


class IncidentCreate(IncidentBase):
    pass


class Incident(IncidentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(gt=0)
    status: IncidentStatus
    created_at: datetime
    updated_at: datetime


class StatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: IncidentStatus


class IncidentSummary(BaseModel):
    total: int
    by_status: dict[str, int]
    by_category: dict[str, int]
    by_origin: dict[str, int]
    by_branch: dict[str, int]
