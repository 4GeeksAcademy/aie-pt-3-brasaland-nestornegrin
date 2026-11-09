"""Las tools del agente contra los routers y repositorios REALES de la API (gestor de incidentes e inventario).

Aquí no se simulan datos: se monta el router real de incidencias (con su `IncidentRepository` sobre un TinyDB
temporal) y el router real de inventario (con su repositorio SQLModel sobre SQLite en memoria), y las tools del agente
los consultan por HTTP con su flujo real de login + Bearer. Solo se sustituyen dos piezas ajenas a las tools:

* `get_current_user` (la verificación del JWT, que depende de `app.main` y de Supabase) se sustituye por un usuario fijo;
* `POST /auth/login` se sustituye por un login mínimo que devuelve un token y comprueba que las tools lo envían.

Esta prueba falla si el contrato de `GET /api/incidents` o `GET /inventory/products` cambia y las tools se quedan atrás.
"""
from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-pytest-do-not-use-in-prod")
os.environ.setdefault("DATABASE_URL", "sqlite://")  # solo para poder importar app.database; no se usa

import pytest
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.incidents.models import IncidentCreate, IncidentStatus
from app.incidents.repository import IncidentRepository
from app.incidents.routes import create_router as create_incidents_router
from app.inventory.models import Ingredient, IngredientEntry, IngredientExit
from app.inventory.routes import create_router as create_inventory_router
from services.agent.tools import (
    BackendClient,
    InventoryQuery,
    InventoryTool,
    TicketQuery,
    TicketTool,
    ToolOutcome,
)

TOKEN = "token-de-integracion"


@pytest.fixture
def real_backend(tmp_path):
    repository = IncidentRepository(tmp_path / "incidents.json")
    first = repository.create(IncidentCreate(title="Nevera sin enfriar", description="La nevera 2 no enfría.",
                                             category="Fallo operativo", origin="branch", branch="Brasaland Laureles"))
    repository.create(IncidentCreate(title="Pedido incompleto", description="Faltan cajas.",
                                     category="Solicitud", origin="internal", branch="central"))
    repository.update_status(str(first.id), IncidentStatus.IN_PROGRESS)

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
    logins: list[str] = []

    @app.post("/auth/login")
    def login() -> dict:
        logins.append("login")
        return {"access_token": TOKEN, "token_type": "bearer"}

    def require_bearer(authorization: str | None = Header(default=None)) -> None:
        if authorization != f"Bearer {TOKEN}":
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

    app.dependency_overrides[get_current_user] = require_bearer
    app.dependency_overrides[get_db] = lambda: Session(engine)
    app.include_router(create_incidents_router(repository))
    app.include_router(create_inventory_router())
    http = TestClient(app, base_url="http://api.test")
    return BackendClient(base_url="http://api.test", email="a@b.co", password="x", http_client=http), repository, logins


def test_ticket_tool_reads_real_incidents(real_backend):
    client, _, logins = real_backend
    tool = TicketTool(client)
    one = tool(TicketQuery(ticket_id=1))
    assert one.outcome is ToolOutcome.OK
    assert (one.tickets[0].title, one.tickets[0].status, one.tickets[0].branch) == (
        "Nevera sin enfriar", "in_progress", "Brasaland Laureles")
    assert tool(TicketQuery(status="open")).tickets[0].title == "Pedido incompleto"
    assert tool(TicketQuery()).total == 2
    assert tool(TicketQuery(ticket_id=999)).outcome is ToolOutcome.NOT_FOUND
    assert logins == ["login"]  # se autentica una vez y reutiliza el token


def test_inventory_tool_reads_real_stock_derived_from_movements(real_backend):
    client, _, _ = real_backend
    result = InventoryTool(client)(InventoryQuery(product_name="pollo"))
    assert result.outcome is ToolOutcome.OK and result.products[0].current_stock == 42  # 50 entradas - 8 salidas
    assert InventoryTool(client)(InventoryQuery(product_name="langosta")).outcome is ToolOutcome.NOT_FOUND


def test_the_tools_do_not_modify_the_services(real_backend):
    client, repository, _ = real_backend
    before = [(item.id, item.status, item.updated_at) for item in repository.list()]
    TicketTool(client)(TicketQuery(ticket_id=1))
    TicketTool(client)(TicketQuery())
    InventoryTool(client)(InventoryQuery())
    assert [(item.id, item.status, item.updated_at) for item in repository.list()] == before


def test_a_wrong_token_is_rejected_by_the_real_service(real_backend):
    client, _, _ = real_backend
    client._token = "otro"  # el servicio responde 401, la tool renueva el token una vez y entonces funciona
    assert TicketTool(client)(TicketQuery(ticket_id=1)).outcome is ToolOutcome.OK
