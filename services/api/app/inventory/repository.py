"""Aggregation queries for Brasaland's inventory.

current_stock is NEVER stored - it is always SUM(entries) - SUM(exits) for
an ingredient. The functions below compute it with a single aggregated
query (GROUP BY / joined subqueries) instead of looping per-ingredient,
to avoid the N+1 query problem when listing many rows at once.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlmodel import Session, select

from .models import Ingredient, IngredientEntry, IngredientExit


def get_current_stock(session: Session, ingredient_id: int) -> float:
    """Stock for a single ingredient - one aggregated query, no loop."""
    entries_total = session.exec(
        select(func.coalesce(func.sum(IngredientEntry.quantity), 0)).where(
            IngredientEntry.ingredient_id == ingredient_id
        )
    ).one()
    exits_total = session.exec(
        select(func.coalesce(func.sum(IngredientExit.quantity), 0)).where(
            IngredientExit.ingredient_id == ingredient_id
        )
    ).one()
    return float(entries_total) - float(exits_total)


def list_ingredients_with_stock(session: Session) -> list[tuple[Ingredient, float]]:
    """All ingredients with their current_stock, computed in one query.

    Avoids N+1: instead of calling get_current_stock() once per ingredient
    in a loop, this aggregates entries and exits per ingredient_id up
    front (as subqueries) and left-joins them onto Ingredient.
    """
    entries_subq = (
        select(
            IngredientEntry.ingredient_id.label("ingredient_id"),
            func.sum(IngredientEntry.quantity).label("total"),
        )
        .group_by(IngredientEntry.ingredient_id)
        .subquery()
    )
    exits_subq = (
        select(
            IngredientExit.ingredient_id.label("ingredient_id"),
            func.sum(IngredientExit.quantity).label("total"),
        )
        .group_by(IngredientExit.ingredient_id)
        .subquery()
    )
    stmt = (
        select(
            Ingredient,
            (
                func.coalesce(entries_subq.c.total, 0)
                - func.coalesce(exits_subq.c.total, 0)
            ).label("current_stock"),
        )
        .outerjoin(entries_subq, entries_subq.c.ingredient_id == Ingredient.id)
        .outerjoin(exits_subq, exits_subq.c.ingredient_id == Ingredient.id)
        .order_by(Ingredient.id)
    )
    results = session.exec(stmt).all()
    return [(row[0], float(row[1])) for row in results]


def list_orders(session: Session) -> list[dict]:
    """All inbound + outbound orders with ingredient name, no N+1.

    Each order type is fetched with its Ingredient joined in the same
    query (not looked up per-row afterwards), then the two lists are
    merged and sorted by date.
    """
    entries_stmt = (
        select(IngredientEntry, Ingredient.name)
        .join(Ingredient, Ingredient.id == IngredientEntry.ingredient_id)
        .order_by(IngredientEntry.created_at.desc())
    )
    exits_stmt = (
        select(IngredientExit, Ingredient.name)
        .join(Ingredient, Ingredient.id == IngredientExit.ingredient_id)
        .order_by(IngredientExit.created_at.desc())
    )

    orders: list[dict] = []
    for entry, ingredient_name in session.exec(entries_stmt).all():
        orders.append(
            {
                "id": entry.id,
                "type": "inbound",
                "ingredient_id": entry.ingredient_id,
                "ingredient_name": ingredient_name,
                "quantity": entry.quantity,
                "created_at": entry.created_at,
                "user_id": entry.user_id,
            }
        )
    for exit_record, ingredient_name in session.exec(exits_stmt).all():
        orders.append(
            {
                "id": exit_record.id,
                "type": "outbound",
                "ingredient_id": exit_record.ingredient_id,
                "ingredient_name": ingredient_name,
                "quantity": exit_record.quantity,
                "created_at": exit_record.created_at,
                "user_id": exit_record.user_id,
            }
        )
    orders.sort(key=lambda o: o["created_at"], reverse=True)
    return orders
