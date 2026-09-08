"""Seed data for Brasaland's inventory (Supabase/SQLModel).

Populates ingredients across two real restaurant locations with entries
and exits that net out to a sensible positive stock, matching the
brief's requirement that seeded stock equals net(entries - exits).

Run with: uv run python -m app.inventory.seed
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from ..database import engine
from .models import Ingredient, IngredientEntry, IngredientExit

# The user_uuid that owns these seed orders. In a real deploy this should
# be an actual operations/admin TinyDB user id.
SEED_USER_ID = 1

INGREDIENTS = [
    {"name": "Carne de res", "sku": "CARNE-RES-POBLADO", "restaurant": "Brasaland El Poblado"},
    {"name": "Papa criolla", "sku": "PAPA-CRIOLLA-POBLADO", "restaurant": "Brasaland El Poblado"},
    {"name": "Chorizo", "sku": "CHORIZO-POBLADO", "restaurant": "Brasaland El Poblado"},
    {"name": "Pollo", "sku": "POLLO-BRICKELL", "restaurant": "Brasaland Brickell"},
]

# (sku, entry_qty, supplier, exit_qty, exit_reason)
MOVEMENTS = [
    ("CARNE-RES-POBLADO", 80, "Distribuidora Carnes del Valle", 30, "Uso en cocina"),
    ("PAPA-CRIOLLA-POBLADO", 150, "AgroFresh Antioquia", 50, "Uso en cocina"),
    ("CHORIZO-POBLADO", 40, "Embutidos San Jose", 10, "Merma por vencimiento"),
    ("POLLO-BRICKELL", 60, "Sysco South Florida", 15, "Uso en cocina"),
]


def seed_inventory() -> None:
    with Session(engine) as session:
        existing = session.exec(select(Ingredient)).first()
        if existing is not None:
            print("Inventory already has data - skipping seed.")
            return

        sku_to_id: dict[str, int] = {}
        for data in INGREDIENTS:
            ingredient = Ingredient(**data)
            session.add(ingredient)
            session.commit()
            session.refresh(ingredient)
            sku_to_id[ingredient.sku] = ingredient.id

        base_time = datetime.now(timezone.utc) - timedelta(days=7)
        for sku, entry_qty, supplier, exit_qty, exit_reason in MOVEMENTS:
            ingredient_id = sku_to_id[sku]
            session.add(
                IngredientEntry(
                    ingredient_id=ingredient_id,
                    quantity=entry_qty,
                    supplier=supplier,
                    created_at=base_time,
                    user_uuid=SEED_USER_ID,
                )
            )
            session.add(
                IngredientExit(
                    ingredient_id=ingredient_id,
                    quantity=exit_qty,
                    reason=exit_reason,
                    created_at=base_time + timedelta(days=2),
                    user_uuid=SEED_USER_ID,
                )
            )
        session.commit()
        print(f"Seeded {len(INGREDIENTS)} ingredients with entries/exits.")


if __name__ == "__main__":
    seed_inventory()
