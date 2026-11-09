"""Contratos tipados de las tools de consulta del agente (tickets e inventario).

Las tools DIRECTAS (`TicketTool`, `InventoryTool`, `BackendClient`) que vivían aquí se ELIMINARON: el agente ya no llama
al gestor de incidentes ni al de inventario, solo al servidor MCP (`services/agent/mcp_tools.py` ->
`mcps/brasaland_mcp`). Aquí quedan únicamente el contrato de entrada/salida y los resultados (`ToolOutcome`), que el
grafo, el enrutamiento y los traces siguen usando sin cambios:

    TicketQuery -> TicketsResult        InventoryQuery -> InventoryResult
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_ITEMS = 10  # tope de filas que una tool devuelve al agente


class ToolOutcome(str, Enum):
    OK = "ok"
    NOT_FOUND = "not_found"  # el recurso no existe (ticket o producto)
    TIMEOUT = "timeout"  # el servicio no respondió a tiempo
    UNAVAILABLE = "unavailable"  # servicio caído, error 5xx o respuesta inesperada
    UNAUTHORIZED = "unauthorized"  # faltan credenciales o el servicio las rechazó
    INVALID = "invalid"  # el servicio rechazó la consulta (400/422)


# --------------------------------------------------------------------------------------------------------------
# Contratos
# --------------------------------------------------------------------------------------------------------------
TicketStatus = Literal["open", "in_progress", "resolved", "discarded"]


class TicketQuery(BaseModel):
    """Entrada de la tool de tickets: un ticket concreto (`ticket_id`) o un listado filtrado por estado."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: int | None = Field(default=None, gt=0)
    status: TicketStatus | None = None
    limit: int = Field(default=5, ge=1, le=MAX_ITEMS)


class TicketInfo(BaseModel):
    """Los mismos campos que expone `GET /api/incidents`."""

    model_config = ConfigDict(extra="ignore")

    id: int
    title: str
    description: str
    category: str
    origin: str
    branch: str
    status: str
    created_at: str
    updated_at: str


class TicketsResult(BaseModel):
    outcome: ToolOutcome
    tickets: list[TicketInfo] = Field(default_factory=list)
    total: int = 0  # coincidencias totales (la lista se recorta a `limit`)
    error: str | None = None


class InventoryQuery(BaseModel):
    """Entrada de la tool de inventario: un producto por `product_id` o por nombre (o todos si no se indica)."""

    model_config = ConfigDict(extra="forbid")

    product_id: int | None = Field(default=None, gt=0)
    product_name: str | None = Field(default=None, min_length=1, max_length=100)
    limit: int = Field(default=MAX_ITEMS, ge=1, le=MAX_ITEMS)


class ProductStock(BaseModel):
    """Los mismos campos que expone `GET /inventory/products`."""

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    sku: str
    restaurant: str
    current_stock: float


class InventoryResult(BaseModel):
    outcome: ToolOutcome
    products: list[ProductStock] = Field(default_factory=list)
    total: int = 0
    error: str | None = None
