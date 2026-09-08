"""SQLModel ORM models for Brasaland's inventory (Supabase/Postgres).

Stock is never stored directly: it is always derived from the sum of
IngredientEntry quantities minus IngredientExit quantities for a given
Ingredient. See app/inventory/repository.py for the aggregation queries.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


class Ingredient(SQLModel, table=True):
    """A kitchen ingredient tracked at a specific Brasaland restaurant.

    Each Ingredient row belongs to exactly one restaurant (e.g. "Brasaland
    El Poblado"), matching Brasaland's real operating model of 14
    independent restaurants across Colombia and the US.
    """

    __tablename__ = "ingredients"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    sku: str = Field(index=True, unique=True)
    restaurant: str = Field(index=True)


class IngredientEntry(SQLModel, table=True):
    """An inbound stock movement (e.g. a supplier delivery)."""

    __tablename__ = "ingredient_entries"

    id: int | None = Field(default=None, primary_key=True)
    ingredient_id: int = Field(foreign_key="ingredients.id", index=True)
    quantity: float
    supplier: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # References the TinyDB user id (int) that created this order. No FK:
    # the users table is not replicated into Supabase.
    user_id: int


class IngredientExit(SQLModel, table=True):
    """An outbound stock movement (e.g. kitchen usage or spoilage)."""

    __tablename__ = "ingredient_exits"

    id: int | None = Field(default=None, primary_key=True)
    ingredient_id: int = Field(foreign_key="ingredients.id", index=True)
    quantity: float
    reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    user_id: int
