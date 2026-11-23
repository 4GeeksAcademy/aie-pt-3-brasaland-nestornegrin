"""Departamentos y reglas de negocio de las RFPs de Brasaland (company-BRIEFING, Hito 9 §2 y §5).

Brasaland no tiene un departamento de «Ventas»: las RFPs corporativas le llegan a Marketing (Camila Ospina), que es quien
abre el ticket. Los identificadores son EXACTOS (los usan el estado del grafo, la base de datos y las Partes 2 y 3).
"""
from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = 1
CEO_APPROVAL_THRESHOLD_USD = 50_000  # BRIEFING §5: contratos por encima de 50.000 USD/año requieren aprobación de la CEO
CEO_NAME = "Mariana Restrepo"

# Estados del ticket que usa ESTA parte (BRIEFING §2.3). Las partes 2 y 3 añaden los suyos.
STATUS_ANALYZING = "analizando"
STATUS_DISCARDED = "descartado"
STATUS_COMPLETE = "analisis_completo"
STATUSES = (STATUS_ANALYZING, STATUS_DISCARDED, STATUS_COMPLETE)


@dataclass(frozen=True)
class Department:
    id: str
    name: str
    owner: str
    contributes: str  # qué aporta a la propuesta (BRIEFING §2.1)
    owns_ticket: bool = False


DEPARTMENTS: dict[str, Department] = {d.id: d for d in (
    Department("marketing", "Marketing y Experiencia Digital", "Camila Ospina",
               "Términos de marca, exclusividad, co-branding, validez de la oferta. Dueña del ticket.", owns_ticket=True),
    Department("operaciones", "Operaciones de Restaurante", "Felipe Guerrero",
               "Viabilidad operativa: capacidad de cocina/personal, tiempos de montaje, costo operativo/evento."),
    Department("procurement", "Procurement y Proveedores", "Lucía Fernández",
               "Costo estimado de insumos según volumen, tiempos de entrega de proveedores."),
    Department("training", "Training y Estándares de Calidad", "Jake Morrison",
               "Si el pedido requiere receta o estándar nuevo, tiempo de desarrollo y certificación necesario."),
)}
DEPARTMENT_IDS = tuple(DEPARTMENTS)
OWNER_DEPARTMENT = next(d.id for d in DEPARTMENTS.values() if d.owns_ticket)

# Cómo se nombran los departamentos en el lenguaje natural de una RFP → id. Sirve para NO inventar departamentos nuevos:
# cualquier nombre que no esté aquí ni sea un id exacto se descarta y se registra (pregunta de diseño del ticket).
ALIASES = {
    "marketing": "marketing", "marca": "marketing", "brand": "marketing", "experiencia digital": "marketing", "ventas": "marketing",
    "sales": "marketing", "comercial": "marketing",
    "operaciones": "operaciones", "operations": "operaciones", "ops": "operaciones", "cocina": "operaciones",
    "procurement": "procurement", "compras": "procurement", "proveedores": "procurement", "suppliers": "procurement",
    "training": "training", "capacitacion": "training", "capacitación": "training", "calidad": "training", "formacion": "training",
}


def resolve_department(name: str) -> str | None:
    key = " ".join(str(name).lower().strip().split())
    if key in DEPARTMENTS:
        return key
    return ALIASES.get(key)


def contact_for(department_id: str) -> dict:
    d = DEPARTMENTS[department_id]
    return {"department_id": d.id, "department": d.name, "owner": d.owner}
