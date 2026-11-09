"""Las tools del servidor MCP. Cada una tiene nombre, descripción y esquema de entrada/salida pensados para que un
agente EXTERNO, sin contexto humano previo, entienda qué puede y qué no puede hacer (se ven con `tools/list`).

    incidents_get_ticket            tickets:read    consulta un ticket por id
    incidents_list_tickets          tickets:read    lista tickets (filtro opcional por estado)
    incidents_create_ticket         tickets:write   crea un ticket        -> POST  /api/incidents
    incidents_update_ticket_status  tickets:write   cambia su estado      -> PATCH /api/incidents/{id}/status
    inventory_get_stock             inventory:read  consulta stock (SOLO LECTURA: no hay forma de modificarlo)

Los campos, ids y valores de dominio son los de las APIs reales de incidentes e inventario.
"""
from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from .backend import IncidentsBackend, InventoryBackend
from .domain import (
    SCOPE_INVENTORY_READ,
    SCOPE_TICKETS_READ,
    SCOPE_TICKETS_WRITE,
    Branch,
    IncidentCategory,
    IncidentOrigin,
    IncidentStatus,
)

MAX_ITEMS = 25

# tool -> scope que exige (lo aplica `middleware.AuditGuardMiddleware`; también se publica en `meta` del discovery).
TOOL_SCOPES: dict[str, str] = {
    "incidents_get_ticket": SCOPE_TICKETS_READ,
    "incidents_list_tickets": SCOPE_TICKETS_READ,
    "incidents_create_ticket": SCOPE_TICKETS_WRITE,
    "incidents_update_ticket_status": SCOPE_TICKETS_WRITE,
    "inventory_get_stock": SCOPE_INVENTORY_READ,
}
INVENTORY_TOOLS = frozenset(name for name in TOOL_SCOPES if name.startswith("inventory_"))
# Argumentos que SÍ acepta cada tool (todo lo demás se rechaza explícitamente, no se ignora).
TOOL_ARGUMENTS: dict[str, frozenset[str]] = {
    "incidents_get_ticket": frozenset({"ticket_id"}),
    "incidents_list_tickets": frozenset({"status", "limit"}),
    "incidents_create_ticket": frozenset({"title", "description", "category", "origin", "branch"}),
    "incidents_update_ticket_status": frozenset({"ticket_id", "status"}),
    "inventory_get_stock": frozenset({"product_name", "product_id", "limit"}),
}


# --- salida (mismos campos que `GET /api/incidents` y `GET /inventory/products`) ----------------------------------
class Ticket(BaseModel):
    id: int = Field(description="Identificador del ticket en el gestor de incidentes.")
    title: str
    description: str
    category: str = Field(description="Queja, Solicitud o Fallo operativo.")
    origin: str = Field(description="customer, branch o internal.")
    branch: str = Field(description="'central' o el nombre de la sede (p. ej. 'Brasaland Laureles').")
    status: str = Field(description="open, in_progress, resolved o discarded.")
    created_at: str = Field(description="Fecha de creación, ISO 8601 (UTC).")
    updated_at: str = Field(description="Última actualización, ISO 8601 (UTC).")


class TicketList(BaseModel):
    total: int = Field(description="Tickets que cumplen el filtro (la lista se recorta a `limit`).")
    tickets: list[Ticket]


class ProductStock(BaseModel):
    id: int = Field(description="Identificador del ingrediente en el inventario.")
    name: str
    sku: str
    restaurant: str = Field(description="Sede a la que pertenece el ingrediente.")
    current_stock: float = Field(description="Stock actual (entradas menos salidas).")


class StockResult(BaseModel):
    total: int = Field(description="Productos que coinciden (la lista se recorta a `limit`).")
    products: list[ProductStock]


def register_tools(mcp: FastMCP, incidents: IncidentsBackend, inventory: InventoryBackend) -> FastMCP:
    def meta(name: str) -> dict:
        return {"required_scope": TOOL_SCOPES[name]}

    @mcp.tool(
        name="incidents_get_ticket",
        description=(
            "Consulta UN ticket de soporte del gestor de incidentes de Brasaland por su id numérico y devuelve su estado "
            "actual (open, in_progress, resolved o discarded), categoría, origen, sede y fechas. Solo lectura. "
            "Errores: NOT_FOUND si el ticket no existe. Requiere el scope tickets:read."),
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        meta=meta("incidents_get_ticket"))
    async def incidents_get_ticket(
        ticket_id: Annotated[int, Field(gt=0, description="Id numérico del ticket (p. ej. 94).")],
    ) -> Ticket:
        return Ticket.model_validate(await incidents.get(f"/api/incidents/{ticket_id}"))

    @mcp.tool(
        name="incidents_list_tickets",
        description=(
            "Lista tickets del gestor de incidentes, del más reciente al más antiguo, con filtro opcional por estado. "
            f"Devuelve como máximo `limit` tickets (por defecto 10, máximo {MAX_ITEMS}) y el total que cumple el filtro. "
            "Solo lectura. Requiere el scope tickets:read."),
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        meta=meta("incidents_list_tickets"))
    async def incidents_list_tickets(
        status: Annotated[IncidentStatus | None, Field(description="Filtra por estado. Omítelo para no filtrar.")] = None,
        limit: Annotated[int, Field(ge=1, le=MAX_ITEMS, description="Máximo de tickets a devolver.")] = 10,
    ) -> TicketList:
        rows = await incidents.get("/api/incidents", {"status": status} if status else None)
        return TicketList(total=len(rows), tickets=[Ticket.model_validate(row) for row in rows[:limit]])

    @mcp.tool(
        name="incidents_create_ticket",
        description=(
            "Crea un ticket nuevo en el gestor de incidentes (POST /api/incidents). Nace siempre en estado `open`. "
            "Todos los campos son obligatorios y sus valores deben ser los del dominio de Brasaland (ver el esquema). "
            "Devuelve el ticket creado con su id. Escritura: no es idempotente (repetir la llamada crea otro ticket). "
            "Requiere el scope tickets:write."),
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        meta=meta("incidents_create_ticket"))
    async def incidents_create_ticket(
        title: Annotated[str, Field(min_length=1, max_length=200, description="Título corto del problema.")],
        description: Annotated[str, Field(min_length=1, max_length=2000, description="Descripción del problema.")],
        category: Annotated[IncidentCategory, Field(description="Queja, Solicitud o Fallo operativo.")],
        origin: Annotated[IncidentOrigin, Field(description="Quién lo reporta: customer, branch o internal.")],
        branch: Annotated[Branch, Field(description="'central' o la sede afectada.")],
    ) -> Ticket:
        created = await incidents.create_ticket(
            {"title": title, "description": description, "category": category, "origin": origin, "branch": branch})
        return Ticket.model_validate(created)

    @mcp.tool(
        name="incidents_update_ticket_status",
        description=(
            "Cambia el estado de un ticket usando el endpoint de ciclo de vida del gestor de incidentes "
            "(PATCH /api/incidents/{id}/status). Transiciones permitidas: open -> in_progress | discarded; "
            "in_progress -> resolved | discarded; resolved y discarded son finales. Pedir el mismo estado actual "
            "no hace nada (idempotente). Errores: NOT_FOUND si el ticket no existe; INVALID_TRANSITION si el ciclo "
            "de vida no permite el cambio. Solo cambia el estado; no edita ningún otro campo. "
            "Requiere el scope tickets:write."),
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        meta=meta("incidents_update_ticket_status"))
    async def incidents_update_ticket_status(
        ticket_id: Annotated[int, Field(gt=0, description="Id numérico del ticket.")],
        status: Annotated[IncidentStatus, Field(description="Estado de destino.")],
    ) -> Ticket:
        return Ticket.model_validate(await incidents.update_ticket_status(ticket_id, status))

    @mcp.tool(
        name="inventory_get_stock",
        description=(
            "Consulta el stock actual de ingredientes en el gestor de inventario (GET /inventory/products). "
            "SOLO LECTURA por diseño: este servidor no ofrece ninguna operación para modificar el inventario y rechaza "
            "explícitamente (READ_ONLY_VIOLATION) cualquier intento de crear, ajustar o borrar existencias. "
            "Filtra por `product_id` o por `product_name` (sin distinguir mayúsculas ni tildes); sin filtros devuelve los "
            "primeros `limit`. Errores: NOT_FOUND si ningún producto coincide. Requiere el scope inventory:read."),
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        meta=meta("inventory_get_stock"))
    async def inventory_get_stock(
        product_name: Annotated[str | None, Field(min_length=1, max_length=100,
                                                  description="Parte del nombre (p. ej. 'pollo').")] = None,
        product_id: Annotated[int | None, Field(gt=0, description="Id numérico del ingrediente.")] = None,
        limit: Annotated[int, Field(ge=1, le=MAX_ITEMS, description="Máximo de productos a devolver.")] = 10,
    ) -> StockResult:
        from ._text import fold

        rows = [ProductStock.model_validate(row) for row in await inventory.get("/inventory/products")]
        if product_id is not None:
            rows = [row for row in rows if row.id == product_id]
        if product_name:
            rows = [row for row in rows if fold(product_name) in fold(row.name)]
        if not rows and (product_id is not None or product_name):
            from . import errors

            raise errors.McpToolError(errors.NOT_FOUND, "Ningún producto del inventario coincide con la consulta.")
        return StockResult(total=len(rows), products=rows[:limit])

    return mcp
