"""Inventory endpoints for Brasaland (Supabase/Postgres via SQLModel).

All routes are registered under the /inventory prefix and require
authentication (both writes and reads - this is internal kitchen/stock
data, not customer-facing), matching the same
dependencies=[Depends(get_current_user)] pattern used by the suppliers
router.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from . import repository
from .models import Ingredient, IngredientEntry, IngredientExit
from .schemas import (
    IngredientCreate,
    IngredientEntryCreate,
    IngredientEntryResponse,
    IngredientExitCreate,
    IngredientExitResponse,
    IngredientResponse,
    OrderResponse,
)


def create_router(prefix: str = "/inventory") -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["inventory"], dependencies=[Depends(get_current_user)])

    @router.get("/products", response_model=list[IngredientResponse])
    def list_products(session: Session = Depends(get_db)) -> list[IngredientResponse]:
        rows = repository.list_ingredients_with_stock(session)
        return [
            IngredientResponse(
                id=ingredient.id,
                name=ingredient.name,
                sku=ingredient.sku,
                restaurant=ingredient.restaurant,
                current_stock=stock,
            )
            for ingredient, stock in rows
        ]

    @router.post("/products", response_model=IngredientResponse, status_code=201)
    def create_product(
        payload: IngredientCreate,
        session: Session = Depends(get_db),
    ) -> IngredientResponse:
        ingredient = Ingredient(name=payload.name, sku=payload.sku, restaurant=payload.restaurant)
        session.add(ingredient)
        session.commit()
        session.refresh(ingredient)
        # A newly created ingredient always starts at zero stock - it can
        # only accumulate stock through IngredientEntry records.
        return IngredientResponse(
            id=ingredient.id,
            name=ingredient.name,
            sku=ingredient.sku,
            restaurant=ingredient.restaurant,
            current_stock=0,
        )

    @router.get("/products/{ingredient_id}", response_model=IngredientResponse)
    def get_product(ingredient_id: int, session: Session = Depends(get_db)) -> IngredientResponse:
        ingredient = session.get(Ingredient, ingredient_id)
        if ingredient is None:
            raise HTTPException(status_code=404, detail="Ingrediente no encontrado")
        stock = repository.get_current_stock(session, ingredient_id)
        return IngredientResponse(
            id=ingredient.id,
            name=ingredient.name,
            sku=ingredient.sku,
            restaurant=ingredient.restaurant,
            current_stock=stock,
        )

    @router.post("/orders/inbound", response_model=IngredientEntryResponse, status_code=201)
    def create_inbound_order(
        payload: IngredientEntryCreate,
        current_user=Depends(get_current_user),
        session: Session = Depends(get_db),
    ) -> IngredientEntryResponse:
        ingredient = session.get(Ingredient, payload.ingredient_id)
        if ingredient is None:
            raise HTTPException(status_code=404, detail="Ingrediente no encontrado")
        entry = IngredientEntry(
            ingredient_id=payload.ingredient_id,
            quantity=payload.quantity,
            supplier=payload.supplier,
            user_uuid=current_user.id,
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return IngredientEntryResponse.model_validate(entry)

    @router.post("/orders/outbound", response_model=IngredientExitResponse, status_code=201)
    def create_outbound_order(
        payload: IngredientExitCreate,
        current_user=Depends(get_current_user),
        session: Session = Depends(get_db),
    ) -> IngredientExitResponse:
        ingredient = session.get(Ingredient, payload.ingredient_id)
        if ingredient is None:
            raise HTTPException(status_code=404, detail="Ingrediente no encontrado")
        # Reject BEFORE persisting if this would take stock negative.
        current_stock = repository.get_current_stock(session, payload.ingredient_id)
        if payload.quantity > current_stock:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Stock insuficiente de '{ingredient.name}' en {ingredient.restaurant}: "
                    f"quedan {current_stock} y se intentaron sacar {payload.quantity}."
                ),
            )
        exit_record = IngredientExit(
            ingredient_id=payload.ingredient_id,
            quantity=payload.quantity,
            reason=payload.reason,
            user_uuid=current_user.id,
        )
        session.add(exit_record)
        session.commit()
        session.refresh(exit_record)
        return IngredientExitResponse.model_validate(exit_record)

    @router.get("/orders", response_model=list[OrderResponse])
    def list_orders(session: Session = Depends(get_db)) -> list[OrderResponse]:
        return [OrderResponse(**row) for row in repository.list_orders(session)]

    return router
