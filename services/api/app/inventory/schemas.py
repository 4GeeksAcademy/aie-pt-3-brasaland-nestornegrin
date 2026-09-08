"""Pydantic request/response schemas for the inventory API.

These are independent classes from the SQLModel ORM models in
app/inventory/models.py - never return an ORM object directly from an
endpoint, always map it into one of these.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class IngredientCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str
    sku: str
    restaurant: str


class IngredientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sku: str
    restaurant: str
    current_stock: float


class IngredientEntryCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    ingredient_id: int
    quantity: float = Field(gt=0)
    supplier: str | None = None


class IngredientEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ingredient_id: int
    quantity: float
    supplier: str | None
    created_at: datetime
    user_uuid: int


class IngredientExitCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    ingredient_id: int
    quantity: float = Field(gt=0)
    reason: str | None = None


class IngredientExitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ingredient_id: int
    quantity: float
    reason: str | None
    created_at: datetime
    user_uuid: int


class OrderResponse(BaseModel):
    """A combined row for GET /inventory/orders (entries + exits)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    ingredient_id: int
    ingredient_name: str
    quantity: float
    created_at: datetime
    user_uuid: int
