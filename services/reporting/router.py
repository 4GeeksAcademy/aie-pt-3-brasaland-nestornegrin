"""Los tres endpoints del pipeline de desempeño de negocio (diseño §9.1).

Cada handler solo valida la petición y llama a una función de `data/pipelines/` (no hay lógica de ETL aquí):

    GET  /reporting/inventory-performance/status   → estado y metadata de la última corrida
    POST /reporting/inventory-performance/runs     → dispara una corrida manual del flow
    GET  /reporting/inventory-performance/kpis     → filas de KPIs de `reporting.restaurant_inventory_daily`

Mismas convenciones que el resto de la API: JWT (`get_current_user`), errores como `{"detail": ...}` y los
parámetros inválidos responden 400. Este módulo es independiente de `app/telemetry/`: no comparte router,
tabla ni código con `GET /telemetry/report`.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from app.auth.dependencies import get_current_user
from app.database import engine
from data.pipelines.inventory_performance import api as pipeline_api
from services.reporting.schemas import KpisResponse, PipelineStatusResponse, RunQueuedResponse, RunRequest


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/reporting/inventory-performance",
        tags=["reporting"],
        dependencies=[Depends(get_current_user)],  # todo el módulo exige sesión, igual que el resto de la API
    )

    @router.get("/status", response_model=PipelineStatusResponse)
    def pipeline_status() -> dict:
        """(1) Estado y metadata de la última corrida del pipeline."""
        return pipeline_api.get_pipeline_status(engine)

    @router.post("/runs", status_code=202, response_model=RunQueuedResponse, responses={409: {"description": "Ya hay una corrida activa"}})
    def trigger_run(payload: RunRequest | None = None, current_user=Depends(get_current_user)):
        """(2) Dispara una corrida manual del flow (opcionalmente de un rango). Responde sin esperar al ETL."""
        body = payload or RunRequest()
        try:
            return pipeline_api.trigger_inventory_performance_run(engine, current_user.id, body.date_from, body.date_to)
        except pipeline_api.PipelineAlreadyRunning as error:
            return JSONResponse(status_code=409, content={"detail": "Ya hay una corrida del pipeline en curso", "run_id": error.run_id})
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get("/kpis", response_model=KpisResponse)
    def inventory_kpis(
        date_from: date | None = Query(default=None, alias="from", description="Primer día (YYYY-MM-DD). Por defecto, hace 14 días."),
        date_to: date | None = Query(default=None, alias="to", description="Último día (YYYY-MM-DD). Por defecto, hoy (UTC)."),
        restaurant: str | None = Query(default=None, description="Nombre exacto del restaurante, p. ej. «Brasaland El Poblado»"),
        country: str | None = Query(default=None, description="País: Colombia | Estados Unidos"),
        granularity: Literal["day", "week"] = Query(default="day"),
    ) -> dict:
        """(3) Filas de KPIs (K1–K6) de la tabla de destino: el feed del dashboard."""
        try:
            return pipeline_api.query_inventory_kpis(
                engine, pipeline_api.KpiFilters(date_from, date_to, restaurant, country, granularity)
            )
        except pipeline_api.InvalidKpiFilters as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    return router
