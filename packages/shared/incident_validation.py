"""Validación compartida del CSV histórico de incidencias postventa (Hito 5).

Única fuente de verdad para qué hace válido un registro del CSV y qué
categorías son válidas en todo el monorepo — la reutilizan:

- ``scripts/analyze.py`` (Hito 5, análisis del CSV)
- ``scripts/seed_incidents.py`` (carga del histórico en el gestor de incidencias)
- ``services/api/app/incidents/models.py`` (categorías del modelo ``Incident``,
  que deben coincidir exactamente con las del CSV histórico)
"""

from __future__ import annotations

from datetime import date

REQUIRED_CSV_FIELDS = (
    "incident_id",
    "customer_name",
    "customer_email",
    "category",
    "status",
    "created_at",
)
OPTIONAL_CSV_FIELDS = ("satisfaction_score",)
VALID_CSV_FIELDS = set(REQUIRED_CSV_FIELDS + OPTIONAL_CSV_FIELDS)

ALLOWED_CATEGORIES = ("Queja", "Solicitud", "Fallo operativo")
ALLOWED_CSV_STATUSES = ("Abierto", "Cerrado", "Descartado")


def validate_incident_row(row: dict[str, str | None]) -> list[str]:
    """Devuelve la lista de motivos de invalidez de una fila del CSV (vacía
    si la fila es válida). Un registro con varios problemas los reporta
    todos, no solo el primero."""
    reasons: list[str] = []
    for field in REQUIRED_CSV_FIELDS:
        if not (row.get(field) or "").strip():
            reasons.append(f"missing_field:{field}")

    category = (row.get("category") or "").strip()
    if category and category not in ALLOWED_CATEGORIES:
        reasons.append("invalid_category")

    status = (row.get("status") or "").strip()
    if status and status not in ALLOWED_CSV_STATUSES:
        reasons.append("invalid_status")

    created_at = (row.get("created_at") or "").strip()
    if created_at:
        try:
            date.fromisoformat(created_at)
        except ValueError:
            reasons.append("invalid_date")

    satisfaction = (row.get("satisfaction_score") or "").strip()
    if satisfaction:
        try:
            score = int(satisfaction)
        except ValueError:
            reasons.append("invalid_satisfaction")
        else:
            if not 1 <= score <= 5:
                reasons.append("invalid_satisfaction")
    return reasons
