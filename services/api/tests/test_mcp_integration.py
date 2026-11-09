"""El servidor MCP (`mcps/brasaland_mcp`) contra los routers y repositorios REALES de la API.

1. Contrato de dominio: los valores que expone el MCP (estados, orígenes, categorías, sedes, transiciones) son LOS MISMOS
   que los de `app.incidents.models`. Si la API cambia y el MCP se queda atrás, esta prueba falla.
2. Los clientes del MCP funcionan contra el gestor de incidentes real (crear, consultar, `PATCH /status`) y el inventario
   real (solo lectura), por HTTP con su login + Bearer. Solo se sustituyen dos piezas ajenas: `get_current_user`
   (depende de Supabase) y `POST /auth/login`.
"""
from __future__ import annotations

import asyncio
import os
import typing

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-pytest-do-not-use-in-prod")
os.environ.setdefault("DATABASE_URL", "sqlite://")

import httpx
import pytest
from fastapi import FastAPI, Header, HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.incidents import models
from app.incidents.repository import IncidentRepository
from app.incidents.routes import create_router as create_incidents_router
from app.inventory.models import Ingredient, IngredientEntry, IngredientExit
from app.inventory.routes import create_router as create_inventory_router
from mcps.brasaland_mcp import domain, errors
from mcps.brasaland_mcp.backend import IncidentsBackend, InventoryBackend, ReadOnlyBackend
from mcps.brasaland_mcp.errors import McpToolError

TOKEN = "token-de-integracion"


# --- 1. contrato de dominio -----------------------------------------------------------------------------------
def test_domain_values_are_the_ones_of_the_incident_api():
    assert set(typing.get_args(domain.IncidentStatus)) == {m.value for m in models.IncidentStatus}
    assert set(typing.get_args(domain.IncidentOrigin)) == {m.value for m in models.IncidentOrigin}
    assert set(typing.get_args(domain.Branch)) == {m.value for m in models.Branch}
    assert set(typing.get_args(domain.IncidentCategory)) == set(domain.CATEGORIES)
    assert {k.value: {v.value for v in vs} for k, vs in models.ALLOWED_TRANSITIONS.items()} == {
        k: set(v) for k, v in domain.LIFECYCLE.items()}


# --- 2. clientes contra los routers reales --------------------------------------------------------------------
@pytest.fixture
def real_api(tmp_path):
    repository = IncidentRepository(tmp_path / "incidents.json")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        pollo = Ingredient(name="Pollo entero", sku="POL-001", restaurant="Brasaland Laureles")
        session.add(pollo)
        session.commit()
        session.add(IngredientEntry(ingredient_id=pollo.id, quantity=50, user_uuid=1))
        session.add(IngredientExit(ingredient_id=pollo.id, quantity=8, user_uuid=1))
        session.commit()

    app = FastAPI()
    requests: list[tuple[str, str]] = []

    @app.middleware("http")
    async def record(request, call_next):
        requests.append((request.method, request.url.path))
        return await call_next(request)

    @app.post("/auth/login")
    def login() -> dict:
        return {"access_token": TOKEN, "token_type": "bearer"}

    def require_bearer(authorization: str | None = Header(default=None)) -> None:
        if authorization != f"Bearer {TOKEN}":
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

    app.dependency_overrides[get_current_user] = require_bearer
    app.dependency_overrides[get_db] = lambda: Session(engine)
    app.include_router(create_incidents_router(repository))
    app.include_router(create_inventory_router())
    transport = httpx.ASGITransport(app=app)

    def backend(cls: type[ReadOnlyBackend]):
        return cls("http://api.test", "a@b.co", "x", transport=transport)

    return backend, repository, requests


NEW = {"title": "Horno apagado", "description": "No enciende.", "category": "Fallo operativo",
       "origin": "branch", "branch": "Brasaland Laureles"}


def test_create_read_and_change_status_through_the_real_incident_api(real_api):
    backend, repository, requests = real_api

    async def flow():
        incidents = backend(IncidentsBackend)
        created = await incidents.create_ticket(NEW)
        assert created["status"] == "open" and created["branch"] == "Brasaland Laureles"
        ticket_id = created["id"]
        moved = await incidents.update_ticket_status(ticket_id, "in_progress")
        assert moved["status"] == "in_progress"
        assert (await incidents.get(f"/api/incidents/{ticket_id}"))["status"] == "in_progress"
        return ticket_id

    ticket_id = asyncio.run(flow())
    assert ("PATCH", f"/api/incidents/{ticket_id}/status") in requests  # el endpoint de ciclo de vida
    assert repository.get(str(ticket_id)).status.value == "in_progress"


def test_the_real_api_rejects_invalid_transitions_and_the_backend_maps_them(real_api):
    backend, _, _ = real_api

    async def flow():
        incidents = backend(IncidentsBackend)
        ticket_id = (await incidents.create_ticket(NEW))["id"]
        with pytest.raises(McpToolError) as error:
            await incidents.update_ticket_status(ticket_id, "resolved")  # open -> resolved no existe
        return error.value

    translated = asyncio.run(flow())  # el cliente ya devuelve el error traducido, con la causa de la API
    assert translated.code == errors.INVALID_TRANSITION


def test_the_real_inventory_is_read_through_get_only(real_api):
    backend, _, requests = real_api
    stock = asyncio.run(backend(InventoryBackend).get("/inventory/products"))
    assert [(p["name"], p["current_stock"]) for p in stock] == [("Pollo entero", 42)]  # 50 entradas - 8 salidas
    assert set(stock[0]) >= {"id", "name", "sku", "restaurant", "current_stock"}
    assert not {name for name in dir(InventoryBackend) if not name.startswith("_")} - {"get", "aclose"}
    assert {method for method, path in requests if path.startswith("/inventory")} == {"GET"}
