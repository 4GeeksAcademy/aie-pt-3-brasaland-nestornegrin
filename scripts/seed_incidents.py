#!/usr/bin/env python3
"""Carga el CSV histórico de incidencias postventa (Hito 5) en el nuevo
gestor de incidencias (services/api), asignando origin="customer" a todos
los registros y reutilizando la validación compartida de
packages/shared/incident_validation.py (la misma que usa scripts/analyze.py,
sin duplicarla).

Idempotente: cada fila válida se mapea a un título único
"Incidencia histórica {incident_id}"; si ya existe un incidente con ese
título, la fila se omite en vez de duplicarse.

Uso (desde la raíz del repo):
    uv run --project services/api python scripts/seed_incidents.py
"""

from __future__ import annotations

import csv
import io
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
API_DIR = REPO_ROOT / "services" / "api"
for path in (REPO_ROOT, API_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from packages.shared.incident_validation import validate_incident_row  # noqa: E402

from app.database import INCIDENTS_DATABASE_PATH  # noqa: E402
from app.incidents.models import IncidentCategory, IncidentOrigin, IncidentStatus, Branch  # noqa: E402
from app.incidents.repository import IncidentRepository  # noqa: E402

DEFAULT_CSV_PATH = REPO_ROOT / "data" / "raw" / "incidents-COMPANY.csv"

# El histórico usa "Abierto/Cerrado/Descartado"; el gestor nuevo usa el ciclo
# de vida open/in_progress/resolved/discarded. No existe equivalente para
# in_progress en datos históricos, lo cual es correcto: nace como
# resuelto/descartado o se deja abierto para retomarlo hoy.
STATUS_MAP = {
    "Abierto": IncidentStatus.OPEN,
    "Cerrado": IncidentStatus.RESOLVED,
    "Descartado": IncidentStatus.DISCARDED,
}


def _build_title(incident_id: str) -> str:
    return f"Incidencia histórica {incident_id}"


def _build_description(row: dict[str, str]) -> str:
    parts = [
        f"Incidencia importada del histórico de postventa (Hito 5).",
        f"Categoría original: {row['category'].strip()}.",
        f"Fecha original: {row['created_at'].strip()}.",
    ]
    score = (row.get("satisfaction_score") or "").strip()
    if score:
        parts.append(f"Satisfacción registrada: {score}/5.")
    # Deliberadamente NO se incluyen customer_name/customer_email: no forman
    # parte del modelo de Incident y son datos personales que no deben
    # copiarse a un campo de texto libre.
    return " ".join(parts)


def seed_incidents(csv_path: Path = DEFAULT_CSV_PATH) -> None:
    try:
        repository = IncidentRepository(INCIDENTS_DATABASE_PATH)
    except OSError as error:
        raise RuntimeError(f"No se pudo abrir la base de datos de incidencias: {error}") from error

    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            content = handle.read()
    except OSError as error:
        raise RuntimeError(f"No se pudo leer el fichero CSV ({csv_path}): {error}") from error
    except UnicodeDecodeError as error:
        raise RuntimeError(f"El fichero CSV no está codificado en UTF-8 ({csv_path}): {error}") from error

    reader = csv.DictReader(io.StringIO(content, newline=""))

    inserted = 0
    already_existed = 0
    invalid = 0
    invalid_reasons: dict[str, int] = {}

    for row_number, row in enumerate(reader, start=2):  # la fila 1 es la cabecera
        try:
            reasons = validate_incident_row(row)
            if reasons:
                invalid += 1
                for reason in reasons:
                    invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1
                continue

            title = _build_title(row["incident_id"].strip())
            if repository.get_by_title(title) is not None:
                already_existed += 1
                continue

            created_at_iso = datetime.fromisoformat(row["created_at"].strip()).replace(tzinfo=timezone.utc).isoformat()
            payload = {
                "title": title,
                "description": _build_description(row),
                "category": IncidentCategory(row["category"].strip()).value,
                "origin": IncidentOrigin.CUSTOMER.value,
                "branch": Branch.CENTRAL.value,
                "status": STATUS_MAP[row["status"].strip()].value,
            }
            repository.insert_historical(payload, created_at_iso)
            inserted += 1
        except (ValueError, KeyError) as error:
            # Una fila individual malformada de un modo que la validación no
            # anticipó no debe tumbar el resto del lote: se cuenta como
            # inválida y se informa en stderr, y se sigue con la siguiente.
            invalid += 1
            invalid_reasons["unexpected_row_error"] = invalid_reasons.get("unexpected_row_error", 0) + 1
            print(f"Advertencia: fila {row_number} omitida por error inesperado: {error}", file=sys.stderr)

    print(
        f"Seed de incidencias completado: {inserted} insertadas, "
        f"{already_existed} ya existían, {invalid} inválidas (omitidas)."
    )
    if invalid_reasons:
        print("Motivos de invalidación:")
        for reason, count in sorted(invalid_reasons.items()):
            print(f"  {reason}: {count}")


def main() -> int:
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV_PATH
    if not csv_path.exists():
        print(f"Error: no se encontró el CSV en {csv_path}", file=sys.stderr)
        return 2
    try:
        seed_incidents(csv_path)
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
