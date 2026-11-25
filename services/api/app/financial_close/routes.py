"""Endpoints del cierre financiero mensual. Los routers SOLO validan identidad/permiso y delegan en `data/pipelines/financial_close/`.
Identidad: el correo del JWT se cruza con el directorio; ser `admin` de la plataforma NO da poder de aprobar (solo Felipe Guerrero).
Datos sensibles (salarios individuales, datos bancarios): se redactan al ingerir, por lo que nunca salen por aquí.

    GET  /financial-close/reports                          informes visibles para ti (pendiente/rechazado: solo el revisor)
    GET  /financial-close/reports/{id}                     informe completo (JSON + Markdown)
    GET  /financial-close/reports/{id}/figures/{figure_id} origen de una cifra (fórmula + registros)
    POST /financial-close/reports/{id}/review              aprobar / rechazar con comentarios (solo el revisor)
    POST /financial-close/demo                             genera CSV de ejemplo, ingesta y prepara el informe (v1)
    POST /financial-close/schedule/tick                    ¿toca ya? lanza el cierre programado (idempotente)
    GET  /financial-close/audit/events                     qué hizo el agente (proceso automático) y quién revisó
    GET  /financial-close/audit/messages                   mensajes enviados (ya redactados)"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from data.pipelines.financial_close import config, generate, schedule
from data.pipelines.financial_close.store import CloseStore, DataStore
from data.pipelines.financial_close.workflow import CloseEngine, WorkflowError

from ..auth.dependencies import get_current_user

_engine: CloseEngine | None = None


def get_engine() -> CloseEngine:
    global _engine
    if _engine is None:
        _engine = CloseEngine(DataStore(os.environ.get("FINANCIAL_DATA_DB") or config.DEFAULT_DATA_DB),
                              CloseStore(os.environ.get("FINANCIAL_CLOSE_DB") or config.DEFAULT_CLOSE_DB))
    return _engine


def set_engine(engine: CloseEngine | None) -> None:
    """Para las pruebas: inyecta un motor con bases temporales."""
    global _engine
    _engine = engine


class _Out(BaseModel):
    model_config = ConfigDict(extra="allow")


class ReportSummaryOut(_Out):
    id: int
    period: str
    version: int
    status: str
    content_hash: str
    created_at: str
    decided_at: str | None = None
    distributed_at: str | None = None


class ReportOut(ReportSummaryOut):
    markdown: str
    content: dict
    reviews: list[dict]


class FigureOut(_Out):
    id: str
    label: str
    value: str | None = None
    unit: str
    formula: str
    status: str
    sources: list[dict]
    records: list[dict]


class EventOut(_Out):
    id: int
    ts: str
    actor_type: str
    actor_id: str
    action: str
    subject: str
    detail: dict


class MessageOut(_Out):
    id: int
    ts: str
    kind: str
    recipient_id: str
    report_id: int
    subject: str
    body: str


class TickOut(_Out):
    ran: bool
    period: str


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=2000)


def create_router() -> APIRouter:
    router = APIRouter(prefix="/financial-close", tags=["financial-close"])

    def need_staff(user, engine: CloseEngine) -> dict:
        staff = engine.close.staff_by_email(str(user.email))
        if staff is None:
            raise HTTPException(status_code=403, detail="Solo el equipo directivo (directorio) accede al cierre financiero.")
        return staff

    def need_role(user, engine: CloseEngine, *roles: str) -> dict:
        staff = need_staff(user, engine)
        if staff["role"] not in roles:
            raise HTTPException(status_code=403, detail="Tu rol no puede hacer esta operación.")
        return staff

    def visible(engine: CloseEngine, report_id: int, staff: dict) -> dict:
        try:
            rep = engine.get(report_id)
        except WorkflowError as e:
            raise HTTPException(status_code=e.status, detail=str(e))
        if not engine.can_view(rep, staff):
            raise HTTPException(status_code=403, detail="Este informe aún no está aprobado: solo lo ve el revisor.")
        return rep

    @router.get("/reports", response_model=list[ReportSummaryOut])
    def reports(user=Depends(get_current_user)):
        engine = get_engine()
        staff = need_staff(user, engine)
        return [r for r in engine.list_reports() if engine.can_view(r, staff)]

    @router.get("/reports/{report_id}", response_model=ReportOut)
    def report(report_id: int, user=Depends(get_current_user)):
        engine = get_engine()
        return visible(engine, report_id, need_staff(user, engine))

    @router.get("/reports/{report_id}/figures/{figure_id}", response_model=FigureOut)
    def figure(report_id: int, figure_id: str, user=Depends(get_current_user)):
        engine = get_engine()
        visible(engine, report_id, need_staff(user, engine))
        try:
            return engine.figure(report_id, figure_id)
        except WorkflowError as e:
            raise HTTPException(status_code=e.status, detail=str(e))

    @router.post("/reports/{report_id}/review", response_model=ReportOut)
    def review(report_id: int, body: ReviewIn, user=Depends(get_current_user)):
        engine = get_engine()
        staff = need_staff(user, engine)
        try:
            return engine.review(report_id, staff, body.decision, body.comment or "")
        except WorkflowError as e:
            raise HTTPException(status_code=e.status, detail=str(e))

    @router.post("/demo", response_model=ReportOut, status_code=201)
    def demo(user=Depends(get_current_user)):
        engine = get_engine()
        need_role(user, engine, *config.OPERATOR_ROLES)
        out = Path(os.environ.get("FINANCIAL_CLOSE_FILES_DIR") or config.DEFAULT_FILES_DIR)
        info = generate.generate(out, date.today())
        engine.load_period(out, info["period"])
        return engine.run_close(info["period"])

    @router.post("/schedule/tick", response_model=TickOut)
    def tick(user=Depends(get_current_user)):
        engine = get_engine()
        need_role(user, engine, *config.OPERATOR_ROLES)
        src = Path(os.environ.get("FINANCIAL_CLOSE_FILES_DIR") or config.DEFAULT_FILES_DIR)
        return schedule.tick(engine, datetime.now(timezone.utc), src if (src / "ledger.csv").exists() else None)

    @router.get("/audit/events", response_model=list[EventOut])
    def audit_events(user=Depends(get_current_user)):
        engine = get_engine()
        need_role(user, engine, *config.AUDIT_ROLES)
        return engine.close.events(300)

    @router.get("/audit/messages", response_model=list[MessageOut])
    def audit_messages(user=Depends(get_current_user)):
        engine = get_engine()
        need_role(user, engine, *config.AUDIT_ROLES)
        return engine.close.messages()[-300:]

    return router
