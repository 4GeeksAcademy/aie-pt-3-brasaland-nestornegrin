"""Seeder de carga: genera proveedores e incidencias con datos variados.

Sirve para medir el API con un volumen realista (los datos de demo son 10
proveedores y 90 incidencias: con tan poco, ningún endpoint es lento y el log
de timing no revela dónde la caché aporta valor).

Escribe en una carpeta APARTE (--data-dir), nunca en los datos de desarrollo:

    python seed_load.py --data-dir /tmp/brasaland-load --suppliers 1500 --incidents 8000
    BRASALAND_DATA_DIR=/tmp/brasaland-load uvicorn app.main:app

Es reproducible (--seed fija el generador aleatorio) y no sobrescribe una
carpeta con datos salvo que se pase --reset.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
API_DIR = Path(__file__).resolve().parent
for path in (REPO_ROOT, API_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from tinydb import TinyDB  # noqa: E402

from app.incidents.models import Branch, IncidentCategory, IncidentOrigin, IncidentStatus  # noqa: E402
from app.suppliers.models import SupplierCategory, SupplierStatus  # noqa: E402

SUPPLIER_PREFIXES = ["Carnes", "Frigorífico", "Frescos", "Lácteos", "Granos", "Distribuidora", "Agro", "Empaques", "Bebidas", "Cold Supply", "Prime", "Sunshine"]
SUPPLIER_PLACES = ["Andinas", "del Valle", "de Antioquia", "La Sabana", "del Caribe", "Orlando", "Miami", "Florida", "Tropical", "Bogotá", "Medellín", "Cali"]
COUNTRIES = {"Colombia": 0.6, "Estados Unidos": 0.4}
INCIDENT_SUBJECTS = ["Nevera", "Freidora", "Parrilla", "Caja registradora", "Aire acondicionado", "Entrega de proveedor", "Pedido de cliente", "Terraza", "Campana extractora", "Datáfono"]
INCIDENT_PROBLEMS = ["averiada", "con retraso", "con fallo intermitente", "sin respuesta", "dañada", "con quejas de clientes", "pendiente de revisión"]
STATUS_WEIGHTS = {IncidentStatus.OPEN: 0.35, IncidentStatus.IN_PROGRESS: 0.2, IncidentStatus.RESOLVED: 0.4, IncidentStatus.DISCARDED: 0.05}


def build_suppliers(count: int, rng: random.Random) -> list[dict]:
    now = datetime.now(timezone.utc)
    rows = []
    for index in range(count):
        category = rng.choice(list(SupplierCategory))
        country = rng.choices(list(COUNTRIES), weights=list(COUNTRIES.values()))[0]
        rows.append({
            "name": f"{rng.choice(SUPPLIER_PREFIXES)} {rng.choice(SUPPLIER_PLACES)} #{index + 1}",
            "categories": [category.value] + ([rng.choice(list(SupplierCategory)).value] if rng.random() < 0.25 else []),
            "country": country,
            "rate": round(rng.uniform(0.2, 30.0), 2),
            "status": (SupplierStatus.ACTIVO if rng.random() < 0.88 else SupplierStatus.SUSPENDIDO).value,
            "updated_at": (now - timedelta(days=rng.randint(0, 365), minutes=rng.randint(0, 1440))).isoformat(),
        })
    # Sin duplicar categorías dentro de un mismo proveedor.
    for row in rows:
        row["categories"] = list(dict.fromkeys(row["categories"]))
    return rows


def build_incidents(count: int, rng: random.Random) -> list[dict]:
    now = datetime.now(timezone.utc)
    categories = [category.value for category in IncidentCategory]
    branches = [branch.value for branch in Branch]
    statuses = list(STATUS_WEIGHTS)
    rows = []
    for index in range(count):
        created = now - timedelta(days=rng.randint(0, 365), minutes=rng.randint(0, 1440))
        status = rng.choices(statuses, weights=list(STATUS_WEIGHTS.values()))[0]
        subject = rng.choice(INCIDENT_SUBJECTS)
        rows.append({
            "title": f"{subject} {rng.choice(INCIDENT_PROBLEMS)} (#{index + 1})",
            "description": f"Incidencia de carga #{index + 1}: {subject.lower()} reportada por el equipo de sala. " * rng.randint(1, 3),
            "category": rng.choice(categories),
            "origin": rng.choice(list(IncidentOrigin)).value,
            "branch": rng.choice(branches),
            "status": status.value,
            "created_at": created.isoformat(),
            "updated_at": (created + timedelta(hours=rng.randint(0, 72))).isoformat(),
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", required=True, type=Path, help="carpeta de destino (nunca services/api)")
    parser.add_argument("--suppliers", type=int, default=1500)
    parser.add_argument("--incidents", type=int, default=8000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--reset", action="store_true", help="vaciar los ficheros de destino si ya tienen datos")
    args = parser.parse_args()

    if args.data_dir.resolve() == API_DIR:
        parser.error("--data-dir no puede ser services/api: ahí viven los datos de desarrollo")
    args.data_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    for filename, rows in (
        ("suppliers.json", build_suppliers(args.suppliers, rng)),
        ("incidents.json", build_incidents(args.incidents, rng)),
    ):
        database = TinyDB(args.data_dir / filename, indent=2)
        if len(database) and not args.reset:
            parser.error(f"{filename} ya tiene {len(database)} filas; usa --reset para sobrescribir")
        database.truncate()
        database.insert_multiple(rows)  # una sola escritura: insertar de uno en uno reescribe el fichero cada vez
        print(f"{filename}: {len(rows)} filas")
        database.close()


if __name__ == "__main__":
    main()
