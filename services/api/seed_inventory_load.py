"""Seeder de carga para el inventario (Postgres/Supabase).

Crea ingredientes de prueba (SKU con prefijo ``LOAD-``) y muchos movimientos
de entrada y salida, para medir ``/inventory/products`` y ``/inventory/orders``
con un volumen realista. Usa el DATABASE_URL del entorno (el de tu .env).

    python seed_inventory_load.py --ingredients 300 --movements 20000
    python seed_inventory_load.py --cleanup        # borra SOLO lo que empieza por LOAD-

Es idempotente: si ya existen ingredientes LOAD-, aborta salvo que se use
--cleanup antes. Nunca toca ingredientes que no tengan el prefijo LOAD-.
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

from sqlalchemy import delete  # noqa: E402
from sqlmodel import Session, SQLModel, select  # noqa: E402

from app.database import engine  # noqa: E402
from app.inventory.models import Ingredient, IngredientEntry, IngredientExit  # noqa: E402

PREFIX = "LOAD-"
RESTAURANTS = ["Brasaland El Poblado", "Brasaland Brickell", "Brasaland Laureles", "Brasaland Orlando", "Brasaland Chapinero"]
NAMES = ["Carne de res", "Pollo", "Chorizo", "Papa criolla", "Yuca", "Plátano", "Arepa", "Queso", "Aguacate", "Aceite", "Arroz", "Frijol", "Cerdo", "Limón", "Cebolla"]
SUPPLIERS = ["Distribuidora Carnes del Valle", "AgroFresh Antioquia", "Embutidos San Jose", "Sysco South Florida", "Frescos del Caribe"]
REASONS = ["Uso en cocina", "Merma por vencimiento", "Transferencia a otra sede"]


def cleanup() -> None:
    with Session(engine) as session:
        ids = [i for i in session.exec(select(Ingredient.id).where(Ingredient.sku.like(f"{PREFIX}%")))]
        if ids:
            session.exec(delete(IngredientEntry).where(IngredientEntry.ingredient_id.in_(ids)))
            session.exec(delete(IngredientExit).where(IngredientExit.ingredient_id.in_(ids)))
            session.exec(delete(Ingredient).where(Ingredient.id.in_(ids)))
        session.commit()
    print(f"Borrados {len(ids)} ingredientes LOAD- y sus movimientos.")


def seed(ingredients: int, movements: int, seed_value: int) -> None:
    rng = random.Random(seed_value)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        if session.exec(select(Ingredient.id).where(Ingredient.sku.like(f"{PREFIX}%"))).first():
            raise SystemExit("Ya hay datos LOAD-. Ejecuta primero: python seed_inventory_load.py --cleanup")
        items = [
            Ingredient(name=f"{rng.choice(NAMES)} {n}", sku=f"{PREFIX}{n:05d}", restaurant=rng.choice(RESTAURANTS))
            for n in range(1, ingredients + 1)
        ]
        session.add_all(items)
        session.commit()
        ids = [item.id for item in items]
        now = datetime.now(timezone.utc)
        entries, exits = [], []
        for _ in range(movements):
            when = now - timedelta(days=rng.randint(0, 180), minutes=rng.randint(0, 1440))
            ingredient_id = rng.choice(ids)
            if rng.random() < 0.45:  # más salidas que entradas por unidad, pero cantidades menores
                exits.append(IngredientExit(ingredient_id=ingredient_id, quantity=round(rng.uniform(1, 20), 1), reason=rng.choice(REASONS), created_at=when, user_uuid=1))
            else:
                entries.append(IngredientEntry(ingredient_id=ingredient_id, quantity=round(rng.uniform(10, 120), 1), supplier=rng.choice(SUPPLIERS), created_at=when, user_uuid=1))
        session.add_all(entries)
        session.add_all(exits)
        session.commit()
    print(f"Creados {ingredients} ingredientes, {len(entries)} entradas y {len(exits)} salidas.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ingredients", type=int, default=300)
    parser.add_argument("--movements", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()
    cleanup() if args.cleanup else seed(args.ingredients, args.movements, args.seed)


if __name__ == "__main__":
    main()
