"""Valores de dominio de las APIs reales (incidentes e inventario). NO se inventan: el test
`services/api/tests/test_mcp_domain_contract.py` falla si dejan de coincidir con `services/api/app/incidents/models.py`."""
from __future__ import annotations

from typing import Literal

from packages.shared.incident_validation import ALLOWED_CATEGORIES  # misma fuente que usa la API de incidentes

IncidentStatus = Literal["open", "in_progress", "resolved", "discarded"]
IncidentOrigin = Literal["customer", "branch", "internal"]
IncidentCategory = Literal["Queja", "Solicitud", "Fallo operativo"]
Branch = Literal[
    "central",
    "Brasaland El Poblado",
    "Brasaland Laureles",
    "Brasaland Envigado",
    "Brasaland Sabaneta",
    "Brasaland Usaquén",
    "Brasaland Chapinero",
    "Brasaland Zona Rosa",
    "Brasaland Granada",
    "Brasaland Ciudad Jardín",
    "Brasaland Unicentro",
    "Brasaland Brickell",
    "Brasaland Coral Gables",
    "Brasaland Downtown",
    "Brasaland International Drive",
]

STATUSES = ("open", "in_progress", "resolved", "discarded")
ORIGINS = ("customer", "branch", "internal")
CATEGORIES = tuple(ALLOWED_CATEGORIES)
# Transiciones que acepta `PATCH /api/incidents/{id}/status` (las valida la API; aquí solo se documentan).
LIFECYCLE = {
    "open": ("in_progress", "discarded"),
    "in_progress": ("resolved", "discarded"),
    "resolved": (),
    "discarded": (),
}

# Scopes OAuth (mínimo privilegio): cada tool exige solo el suyo.
SCOPE_TICKETS_READ = "tickets:read"
SCOPE_TICKETS_WRITE = "tickets:write"
SCOPE_INVENTORY_READ = "inventory:read"
ALL_SCOPES = (SCOPE_TICKETS_READ, SCOPE_TICKETS_WRITE, SCOPE_INVENTORY_READ)
