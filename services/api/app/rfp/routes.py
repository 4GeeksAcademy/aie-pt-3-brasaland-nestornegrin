"""Endpoints de las RFPs (Hito 9 · Partes 1, 2 y 3). Los routers SOLO disparan y consultan: la lógica de agentes vive en
`data/pipelines/rfp_intake/` (Parte 1), `rfp_response/` (Parte 2) y `rfp_approval/` (Parte 3).

    POST /rfp/tickets                 sube el PDF → 202 + ticket_id (el pipeline corre en segundo plano)
    GET  /rfp/tickets                 lista de tickets
    GET  /rfp/tickets/{id}            estado en vivo + resultado (la UI hace polling aquí)
    POST /rfp/tickets/{id}/reprocess  reintenta un ticket fallido/detenido o reabre un descartado (?force=true)
    POST /rfp/tickets/{id}/generate   Parte 2: genera/evalúa los borradores (desde analisis_completo; reanuda tras un fallo;
                                      ?regenerate=true descarta los borradores existentes). Se encadena solo al terminar la Parte 1.

    POST /rfp/tickets/{id}/approval/start   Parte 3: abre la aprobación humana (una rama pausada por departamento). Se encadena solo.
    POST /rfp/tickets/{id}/approvals/{dept} Parte 3: resume de ESA rama con la decisión humana (approve | reject | request_changes);
                                            `dept` es un departamento o `ceo`. La respuesta se valida antes de tocar el checkpoint.
    POST /rfp/tickets/{id}/approval/retry   Parte 3: reintenta la convergencia/síntesis tras un fallo (no vuelve a pedir aprobaciones).
    GET  /rfp/tickets/{id}/trace            qué agente hizo qué y en qué orden, de la subida al documento final
    GET  /rfp/tickets/{id}/document         documento final (solo cuando el ticket está `terminado`)

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
from data.pipelines.rfp_approval import ApprovalEngine, InvalidDecision, build_checkpointer
from data.pipelines.rfp_approval import config as part3
from data.pipelines.rfp_approval.packet import ceo_packet, department_packet
from data.pipelines.rfp_response import config as part2
from data.pipelines.rfp_response import generate_ticket

from ..auth.dependencies import get_current_user
from ..database import engine, get_db
from . import repository
from .repository import SqlRfpStore
from .schemas import ApprovalIn, FinalDocumentOut, Progress, SectionOut, TicketDetail, TraceEventOut, TicketSummary, UploadAccepted

REPO_ROOT = Path(__file__).resolve().parents[4]
MAX_PDF_BYTES = 10 * 1024 * 1024
STALL_AFTER = timedelta(minutes=15)  # sin latido durante este tiempo, el ticket se considera detenido


def raw_dir() -> Path:
    return Path(os.environ.get("RFP_RAW_DIR") or REPO_ROOT / "data" / "raw" / "rfp")


def safe_stem(filename: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).stem).strip("-.")[:60]
    return stem or "rfp"


def is_working_status(ticket) -> bool:
    """¿El ticket está en un estado en el que debería haber trabajo en curso? (si no, está «en reposo»)."""
    if ticket.status in (STATUS_ANALYZING, part2.STATUS_GENERATING):
        return True
    if ticket.status == part3.STATUS_AWAITING:  # esperando a un humano ≠ trabajando: solo hay trabajo mientras un nodo corre (current_node)
        return bool(ticket.current_node) or bool(ticket.processing_error)
    return ticket.status == part2.STATUS_EVALUATING and not ticket.response_completed_at  # en_evaluación terminado = todas pasaron


def processing_state(ticket, now: datetime | None = None) -> str:
    if not is_working_status(ticket):
        return "idle"
    if ticket.processing_error:
        return "failed"
    beat = ticket.heartbeat_at or ticket.updated_at
    if beat is not None and beat.tzinfo is None:
        beat = beat.replace(tzinfo=timezone.utc)
    return "stalled" if beat and (now or datetime.now(timezone.utc)) - beat > STALL_AFTER else "running"


def auto_generate() -> bool:
    return os.environ.get("RFP_AUTO_GENERATE", "1").lower() not in ("0", "false", "no")


def auto_review() -> bool:
    return os.environ.get("RFP_AUTO_REVIEW", "1").lower() not in ("0", "false", "no")


def create_router(prefix: str = "/rfp", *, store_factory: Callable[[], SqlRfpStore] | None = None, llm=None, checkpointer=None) -> APIRouter:
    """`store_factory`, `llm` y `checkpointer` son inyectables para las pruebas (por defecto: Supabase, el modelo real y SQLite en archivo)."""
    router = APIRouter(prefix=prefix, tags=["rfp"], dependencies=[Depends(get_current_user)])
    make_store = store_factory or (lambda: SqlRfpStore(lambda: Session(engine)))

    holder: dict = {}

    def get_engine() -> ApprovalEngine:
        """Un solo motor (y un solo checkpointer) por router: las ramas de todos los tickets comparten archivo, no hilos de checkpoint."""
        if "engine" not in holder:
            holder["engine"] = ApprovalEngine(make_store(), llm, checkpointer if checkpointer is not None else build_checkpointer())
        return holder["engine"]

    def run_pipeline(ticket_id: int, force: bool) -> None:
        store = make_store()
        outcome = process_ticket(ticket_id, store, llm, force=force)  # nunca lanza: registra el fallo en el ticket
        if outcome == "completo" and auto_generate():  # Parte 1 terminó: la Parte 2 arranca desde su handoff
            after_generation(ticket_id, generate_ticket(ticket_id, store, llm, mode="start"))

    def run_generation(ticket_id: int, mode: str) -> None:
        after_generation(ticket_id, generate_ticket(ticket_id, make_store(), llm, mode=mode))

    def after_generation(ticket_id: int, outcome: str) -> None:
        if outcome in ("completo", "revision_humana") and auto_review():  # Parte 2 terminó: la Parte 3 abre las aprobaciones
            get_engine().start(ticket_id)

    def run_start_approval(ticket_id: int) -> None:
        get_engine().start(ticket_id)

    def run_resume(ticket_id: int, raw: dict) -> None:
        try:
            get_engine().resume(ticket_id, raw)
        except InvalidDecision:  # ya se validó al recibirla; si el estado cambió entre tanto, no hay nada que reanudar
            pass

    def run_retry(ticket_id: int) -> None:
        get_engine().retry(ticket_id)

    def progress_of(session: Session, t) -> Progress | None:
        if t.status not in (part2.STATUS_GENERATING, part2.STATUS_EVALUATING, part2.STATUS_NEEDS_REVIEW, part3.STATUS_AWAITING, part3.STATUS_DONE):
            return None
        rows = repository.get_sections(session, t.ticket_id)
        status = [r.generation_status for r in rows]
        return Progress(total=len(rows), passed=status.count(part2.SECTION_PASSED), needs_review=status.count(part2.SECTION_NEEDS_REVIEW),
                        working=sum(x in (part2.SECTION_GENERATING, part2.SECTION_EVALUATING, part2.SECTION_PENDING) for x in status),
                        errors=status.count(part2.SECTION_ERROR), approved=sum(r.approval_status == part3.APPROVAL_APPROVED for r in rows),
                        awaiting=sum(r.approval_branch == part3.BRANCH_WAITING for r in rows))

    def summary_of(session: Session, t) -> TicketSummary:
        meta = repository.get_metadata(session, t.ticket_id)
        return TicketSummary(ticket_id=t.ticket_id, rfp_id=t.rfp_id, status=t.status, processing=processing_state(t),
                             original_filename=t.original_filename, client_name=meta.client_name if meta else None,
                             current_node=t.current_node, progress=progress_of(session, t), created_at=t.created_at, updated_at=t.updated_at)

    def review_packets(session: Session, t) -> tuple[dict, dict | None]:
        """Fichas de decisión de las ramas que esperan a un humano (se calculan del estado en la base de datos, no del checkpoint)."""
        if t.status != part3.STATUS_AWAITING:
            return {}, None
        state = make_store().get_part3_input(t.ticket_id)
        packets = {d: department_packet(t.ticket_id, d, sec["approval_round"], sec, state["handoff"], state["ceo"], state["conflicts_log"])
                   for d, sec in state["sections"].items() if sec["approval_branch"] == part3.BRANCH_WAITING}
        ceo = state["ceo"] or {}
        card = ceo_packet(t.ticket_id, ceo.get("round") or 1, state["sections"], state["handoff"], ceo, state["conflicts_log"]) \
            if ceo.get("branch") == part3.BRANCH_WAITING else None
        return packets, card

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
        packets, ceo_card = review_packets(session, t)
        sections = [SectionOut(department_id=s.department_id, department=DEPARTMENTS[s.department_id].name, owner=DEPARTMENTS[s.department_id].owner,
                               reason=s.reason, key_aspects=s.key_aspects, asks=s.asks, figures=s.figures, open_questions=s.open_questions,
                               excerpts=s.excerpts, approval_status=s.approval_status, generation_status=s.generation_status,
                               iterations=s.iterations, needs_human_review=s.needs_human_review, draft_content=s.draft_content,
                               pending_items=s.pending_items, evaluation_results=s.evaluation_results,
                               evaluation_history=s.evaluation_history, generation_error=s.generation_error, approver=s.approver,
                               approved_at=s.approved_at, approval_comment=s.approval_comment, approval_round=s.approval_round,
                               approval_history=s.approval_history, escalated=s.escalated, approval_branch=s.approval_branch,
                               review_packet=packets.get(s.department_id))
                    for s in repository.get_sections(session, ticket_id) if s.department_id in DEPARTMENTS]
        metadata = None
        if meta is not None:
            metadata = {k: getattr(meta, k) for k in ("reference", "client_name", "location", "service_type", "scope", "deadline",
                                                      "deadline_iso", "budget_range", "budget_usd_min", "budget_usd_max",
                                                      "departments_needed", "open_questions")}
        return TicketDetail(**summary_of(session, t).model_dump(), discard_reason=t.discard_reason, processing_error=t.processing_error,
                            attempts=t.attempts, classification=t.classification, metadata=metadata,
                            readability=meta.readability if meta else None, sections=sections, summary=t.summary, handoff=t.handoff,
                            part3_handoff=t.part3_handoff, response_completed_at=t.response_completed_at,
                            ceo_approval=t.ceo_approval, ceo_packet=ceo_card, conflicts=t.conflicts_log, completed_at=t.completed_at,
                            has_final_document=repository.get_final_document(session, ticket_id) is not None)

    @router.post("/tickets/{ticket_id}/reprocess", response_model=UploadAccepted, status_code=202)
    def reprocess(ticket_id: int, background: BackgroundTasks, force: bool = False, session: Session = Depends(get_db)) -> UploadAccepted:
        t = repository.get_ticket(session, ticket_id)
        if t is None:
            raise HTTPException(status_code=404, detail="Ticket no encontrado.")
        working = processing_state(t)
        if t.status == STATUS_ANALYZING and working == "running":
            raise HTTPException(status_code=409, detail="El ticket se está procesando.")
        if t.status != STATUS_DISCARDED and not (t.status == STATUS_ANALYZING and working in ("failed", "stalled")):
            raise HTTPException(status_code=409, detail="Solo se reprocesa un ticket descartado o cuyo análisis falló o se detuvo.")
        if force and t.status != STATUS_DISCARDED:
            raise HTTPException(status_code=409, detail="«Forzar» solo aplica a tickets descartados.")
        background.add_task(run_pipeline, ticket_id, force)
        return UploadAccepted(ticket_id=ticket_id, status=STATUS_ANALYZING)

    @router.post("/tickets/{ticket_id}/generate", response_model=UploadAccepted, status_code=202)
    def generate(ticket_id: int, background: BackgroundTasks, regenerate: bool = False, session: Session = Depends(get_db)) -> UploadAccepted:
        t = repository.get_ticket(session, ticket_id)
        if t is None:
            raise HTTPException(status_code=404, detail="Ticket no encontrado.")
        working = processing_state(t)
        if working == "running":
            raise HTTPException(status_code=409, detail="El ticket se está procesando.")
        if t.status == STATUS_COMPLETE:
            mode = "start"
        elif working in ("failed", "stalled") and t.status in (part2.STATUS_GENERATING, part2.STATUS_EVALUATING):
            mode = "resume"  # conserva las secciones que ya terminaron
        elif t.status in (part2.STATUS_EVALUATING, part2.STATUS_NEEDS_REVIEW):
            if not regenerate:
                raise HTTPException(status_code=409, detail="El ticket ya tiene borradores evaluados; usa regenerate=true para rehacerlos.")
            mode = "regenerate"
        else:
            raise HTTPException(status_code=409, detail="La Parte 2 solo arranca desde un ticket con el análisis completo (analisis_completo).")
        background.add_task(run_generation, ticket_id, mode)
        return UploadAccepted(ticket_id=ticket_id, status=t.status)

    @router.post("/tickets/{ticket_id}/approval/start", response_model=UploadAccepted, status_code=202)
    def start_approval(ticket_id: int, background: BackgroundTasks, session: Session = Depends(get_db)) -> UploadAccepted:
        t = repository.get_ticket(session, ticket_id)
        if t is None:
            raise HTTPException(status_code=404, detail="Ticket no encontrado.")
        if processing_state(t) == "running":
            raise HTTPException(status_code=409, detail="El ticket se está procesando.")
        if t.status not in part3.ENTRY_STATUSES or not (t.part3_handoff or {}).get("ready_for_part_3"):
            raise HTTPException(status_code=409, detail="La aprobación solo arranca desde un ticket con la respuesta generada y evaluada "
                                                        f"({', '.join(part3.ENTRY_STATUSES)}).")
        background.add_task(run_start_approval, ticket_id)
        return UploadAccepted(ticket_id=ticket_id, status=part3.STATUS_AWAITING)

    @router.post("/tickets/{ticket_id}/approvals/{department_id}", response_model=UploadAccepted, status_code=202)
    def decide(ticket_id: int, department_id: str, body: ApprovalIn, background: BackgroundTasks, session: Session = Depends(get_db),
               user=Depends(get_current_user)) -> UploadAccepted:
        if repository.get_ticket(session, ticket_id) is None:
            raise HTTPException(status_code=404, detail="Ticket no encontrado.")
        email = getattr(user, "email", None) or (user.get("email") if isinstance(user, dict) else None)
        raw = {**body.model_dump(), "department_id": department_id, "submitted_by": email}
        try:  # la respuesta humana se valida ANTES de tocar el checkpoint
            get_engine().validate(ticket_id, raw)
        except InvalidDecision as exc:
            raise HTTPException(status_code=409 if exc.code in ("not_awaiting", "not_waiting") else 422, detail=str(exc)) from exc
        background.add_task(run_resume, ticket_id, raw)
        return UploadAccepted(ticket_id=ticket_id, status=part3.STATUS_AWAITING)

    @router.post("/tickets/{ticket_id}/approval/retry", response_model=UploadAccepted, status_code=202)
    def retry_approval(ticket_id: int, background: BackgroundTasks, session: Session = Depends(get_db)) -> UploadAccepted:
        t = repository.get_ticket(session, ticket_id)
        if t is None:
            raise HTTPException(status_code=404, detail="Ticket no encontrado.")
        if t.status != part3.STATUS_AWAITING or processing_state(t) not in ("failed", "stalled"):
            raise HTTPException(status_code=409, detail="Solo se reintenta un ticket en esperando_aprobación cuyo cierre falló o se detuvo.")
        background.add_task(run_retry, ticket_id)
        return UploadAccepted(ticket_id=ticket_id, status=t.status)

    @router.get("/tickets/{ticket_id}/trace", response_model=list[TraceEventOut])
    def trace(ticket_id: int, session: Session = Depends(get_db)) -> list[dict]:
        if repository.get_ticket(session, ticket_id) is None:
            raise HTTPException(status_code=404, detail="Ticket no encontrado.")
        return make_store().list_events(ticket_id)

    @router.get("/tickets/{ticket_id}/document", response_model=FinalDocumentOut)
    def final_document(ticket_id: int, session: Session = Depends(get_db)):
        if repository.get_ticket(session, ticket_id) is None:
            raise HTTPException(status_code=404, detail="Ticket no encontrado.")
        doc = repository.get_final_document(session, ticket_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="El documento final aún no existe: faltan aprobaciones.")
        return doc

    return router
