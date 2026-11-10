"""Endpoints de la recepción de RFPs (Hito 9 · Parte 1). Los routers SOLO disparan y consultan: la lógica de agentes vive en
`data/pipelines/rfp_intake/`.

    POST /rfp/tickets                 sube el PDF → 202 + ticket_id (el pipeline corre en segundo plano)
    GET  /rfp/tickets                 lista de tickets
    GET  /rfp/tickets/{id}            estado en vivo + resultado (la UI hace polling aquí)
    POST /rfp/tickets/{id}/reprocess  reintenta un ticket fallido/detenido o reabre un descartado (?force=true)

Dónde corre el trabajo: `BackgroundTasks` de FastAPI (hilo del mismo proceso). Es suficiente para este volumen y no añade
infraestructura; su límite es que un reinicio del proceso mata el trabajo en curso. Por eso la VERDAD está en PostgreSQL:
cada nodo escribe un latido y, si el latido se detiene, el ticket se muestra como «detenido» y puede reprocesarse.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlmodel import Session

from data.pipelines.rfp_intake import process_ticket
from data.pipelines.rfp_intake.departments import (DEPARTMENTS, STATUS_ANALYZING, STATUS_COMPLETE, STATUS_DISCARDED)

from ..auth.dependencies import get_current_user
from ..database import engine, get_db
from . import repository
from .repository import SqlRfpStore
from .schemas import SectionOut, TicketDetail, TicketSummary, UploadAccepted

REPO_ROOT = Path(__file__).resolve().parents[4]
MAX_PDF_BYTES = 10 * 1024 * 1024
STALL_AFTER = timedelta(minutes=15)  # sin latido durante este tiempo, el ticket se considera detenido


def raw_dir() -> Path:
    return Path(os.environ.get("RFP_RAW_DIR") or REPO_ROOT / "data" / "raw" / "rfp")


def safe_stem(filename: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).stem).strip("-.")[:60]
    return stem or "rfp"


def processing_state(ticket, now: datetime | None = None) -> str:
    if ticket.status != STATUS_ANALYZING:
        return "idle"
    if ticket.processing_error:
        return "failed"
    beat = ticket.heartbeat_at or ticket.updated_at
    if beat is not None and beat.tzinfo is None:
        beat = beat.replace(tzinfo=timezone.utc)
    return "stalled" if beat and (now or datetime.now(timezone.utc)) - beat > STALL_AFTER else "running"


def create_router(prefix: str = "/rfp", *, store_factory: Callable[[], SqlRfpStore] | None = None, llm=None) -> APIRouter:
    """`store_factory` y `llm` son inyectables para las pruebas (por defecto: Supabase y el modelo real)."""
    router = APIRouter(prefix=prefix, tags=["rfp"], dependencies=[Depends(get_current_user)])
    make_store = store_factory or (lambda: SqlRfpStore(lambda: Session(engine)))

    def run_pipeline(ticket_id: int, force: bool) -> None:
        process_ticket(ticket_id, make_store(), llm, force=force)  # nunca lanza: registra el fallo en el ticket

    def summary_of(session: Session, t) -> TicketSummary:
        meta = repository.get_metadata(session, t.ticket_id)
        return TicketSummary(ticket_id=t.ticket_id, rfp_id=t.rfp_id, status=t.status, processing=processing_state(t),
                             original_filename=t.original_filename, client_name=meta.client_name if meta else None,
                             current_node=t.current_node, created_at=t.created_at, updated_at=t.updated_at)

    @router.post("/tickets", response_model=UploadAccepted, status_code=202)
    async def upload(background: BackgroundTasks, file: UploadFile = File(...), session: Session = Depends(get_db),
                     user=Depends(get_current_user)) -> UploadAccepted:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=415, detail="El archivo debe ser un PDF.")
        content = await file.read(MAX_PDF_BYTES + 1)
        if not content:
            raise HTTPException(status_code=400, detail="El archivo está vacío.")
        if len(content) > MAX_PDF_BYTES:
            raise HTTPException(status_code=413, detail="El PDF supera el máximo de 10 MB.")
        if not content.startswith(b"%PDF-"):
            raise HTTPException(status_code=415, detail="El archivo no es un PDF válido.")
        directory = raw_dir()
        directory.mkdir(parents=True, exist_ok=True)
        uploader = getattr(user, "email", None) or (user.get("email") if isinstance(user, dict) else None)
        ticket = repository.create_ticket(session, raw_pdf_path="", original_filename=Path(file.filename).name[:200], uploaded_by=uploader)
        path = directory / f"{ticket.ticket_id:05d}-{safe_stem(file.filename)}-{uuid.uuid4().hex[:6]}.pdf"
        path.write_bytes(content)
        repository.set_pdf_path(session, ticket, str(path))
        background.add_task(run_pipeline, ticket.ticket_id, False)
        return UploadAccepted(ticket_id=ticket.ticket_id, status=ticket.status)

    @router.get("/tickets", response_model=list[TicketSummary])
    def list_all(session: Session = Depends(get_db)) -> list[TicketSummary]:
        return [summary_of(session, t) for t in repository.list_tickets(session)]

    @router.get("/tickets/{ticket_id}", response_model=TicketDetail)
    def detail(ticket_id: int, session: Session = Depends(get_db)) -> TicketDetail:
        t = repository.get_ticket(session, ticket_id)
        if t is None:
            raise HTTPException(status_code=404, detail="Ticket no encontrado.")
        meta = repository.get_metadata(session, ticket_id)
        sections = [SectionOut(department_id=s.department_id, department=DEPARTMENTS[s.department_id].name, owner=DEPARTMENTS[s.department_id].owner,
                               reason=s.reason, key_aspects=s.key_aspects, asks=s.asks, figures=s.figures, open_questions=s.open_questions,
                               excerpts=s.excerpts, approval_status=s.approval_status)
                    for s in repository.get_sections(session, ticket_id) if s.department_id in DEPARTMENTS]
        metadata = None
        if meta is not None:
            metadata = {k: getattr(meta, k) for k in ("reference", "client_name", "location", "service_type", "scope", "deadline",
                                                      "deadline_iso", "budget_range", "budget_usd_min", "budget_usd_max",
                                                      "departments_needed", "open_questions")}
        return TicketDetail(**summary_of(session, t).model_dump(), discard_reason=t.discard_reason, processing_error=t.processing_error,
                            attempts=t.attempts, classification=t.classification, metadata=metadata,
                            readability=meta.readability if meta else None, sections=sections, summary=t.summary, handoff=t.handoff)

    @router.post("/tickets/{ticket_id}/reprocess", response_model=UploadAccepted, status_code=202)
    def reprocess(ticket_id: int, background: BackgroundTasks, force: bool = False, session: Session = Depends(get_db)) -> UploadAccepted:
        t = repository.get_ticket(session, ticket_id)
        if t is None:
            raise HTTPException(status_code=404, detail="Ticket no encontrado.")
        if t.status == STATUS_COMPLETE:
            raise HTTPException(status_code=409, detail="El ticket ya tiene el análisis completo.")
        if t.status == STATUS_ANALYZING and processing_state(t) == "running":
            raise HTTPException(status_code=409, detail="El ticket se está procesando.")
        if force and t.status != STATUS_DISCARDED:
            raise HTTPException(status_code=409, detail="«Forzar» solo aplica a tickets descartados.")
        background.add_task(run_pipeline, ticket_id, force)
        return UploadAccepted(ticket_id=ticket_id, status=STATUS_ANALYZING)

    return router
