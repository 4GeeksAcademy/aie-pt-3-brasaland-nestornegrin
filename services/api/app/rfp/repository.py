"""Implementación PostgreSQL (SQLModel) del contrato `RfpStore` del pipeline + consultas para la API.

Cada operación abre su PROPIA sesión corta: el pipeline corre en un hilo de fondo (y los workers en paralelo), así que no se
comparte la sesión de la petición HTTP. `complete` escribe secciones + handoff + estado en UNA transacción: o queda todo o nada.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import delete, update
from sqlmodel import Session, select

from data.pipelines.rfp_intake.departments import STATUS_ANALYZING, STATUS_COMPLETE, STATUS_DISCARDED
from data.pipelines.rfp_approval import config as part3
from data.pipelines.rfp_approval.store import SECTION_FIELDS, TICKET_FIELDS
from data.pipelines.rfp_response import config as part2

from .models import RfpDepartmentSection, RfpFinalDocument, RfpMetadata, RfpTicket, RfpTraceEvent


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SqlRfpStore:
    def __init__(self, session_factory: Callable[[], Session]):
        self._session = session_factory

    # ---- contrato RfpStore -------------------------------------------------------------------------------
    def get_ticket(self, ticket_id: int) -> dict:
        with self._session() as s:
            t = s.get(RfpTicket, ticket_id)
            if t is None:
                raise KeyError(ticket_id)
            return {"ticket_id": t.ticket_id, "status": t.status, "raw_pdf_path": t.raw_pdf_path, "original_filename": t.original_filename,
                    "markdown": t.markdown, "rfp_id": t.rfp_id, "attempts": t.attempts}

    def _update(self, ticket_id: int, **fields) -> None:
        with self._session() as s:
            t = s.get(RfpTicket, ticket_id)
            for k, v in fields.items():
                setattr(t, k, v)
            t.updated_at = _now()
            s.add(t)
            s.commit()

    def begin(self, ticket_id: int) -> None:
        with self._session() as s:
            t = s.get(RfpTicket, ticket_id)
            t.status, t.processing_error, t.discard_reason = STATUS_ANALYZING, None, None
            t.attempts += 1
            t.heartbeat_at, t.current_node, t.updated_at = _now(), "begin", _now()
            s.add(t)
            s.commit()

    def heartbeat(self, ticket_id: int, node: str) -> None:
        self._update(ticket_id, current_node=node, heartbeat_at=_now())

    def save_markdown(self, ticket_id: int, markdown: str) -> None:
        self._update(ticket_id, markdown=markdown)

    def save_classification(self, ticket_id: int, classification: dict) -> None:
        self._update(ticket_id, classification=classification)

    def mark_discarded(self, ticket_id: int, reason: str, classification: dict | None) -> None:
        self._update(ticket_id, status=STATUS_DISCARDED, discard_reason=reason, classification=classification, current_node="discard")

    def save_metadata(self, ticket_id: int, metadata: dict, readability: dict, rfp_id: str) -> None:
        with self._session() as s:
            row = s.exec(select(RfpMetadata).where(RfpMetadata.ticket_id == ticket_id)).first() or RfpMetadata(ticket_id=ticket_id)
            for field in ("reference", "client_name", "location", "service_type", "scope", "deadline", "deadline_iso", "budget_range",
                          "budget_usd_min", "budget_usd_max", "open_questions"):
                setattr(row, field, metadata.get(field))
            row.open_questions = metadata.get("open_questions") or []
            row.readability = readability
            s.add(row)
            t = s.get(RfpTicket, ticket_id)
            t.rfp_id, t.updated_at = rfp_id, _now()
            s.add(t)
            s.commit()

    def complete(self, ticket_id: int, sections: list[dict], handoff: dict, summary: dict, departments_needed: list[str]) -> None:
        with self._session() as s:  # una sola transacción
            s.exec(delete(RfpDepartmentSection).where(RfpDepartmentSection.ticket_id == ticket_id))
            for sec in sections:
                s.add(RfpDepartmentSection(ticket_id=ticket_id, department_id=sec["department_id"], reason=sec.get("reason"),
                                           key_aspects=sec["key_aspects"], asks=sec["asks"], figures=sec["figures"],
                                           open_questions=sec["open_questions"], excerpts=sec["excerpts"]))
            meta = s.exec(select(RfpMetadata).where(RfpMetadata.ticket_id == ticket_id)).first()
            if meta is not None:
                meta.departments_needed = list(departments_needed)
                s.add(meta)
            t = s.get(RfpTicket, ticket_id)
            t.status, t.handoff, t.summary, t.processing_error = STATUS_COMPLETE, handoff, summary, None
            t.current_node, t.heartbeat_at, t.updated_at = "complete", _now(), _now()
            s.add(t)
            s.commit()

    def fail(self, ticket_id: int, message: str) -> None:
        self._update(ticket_id, processing_error=message[:2000])


    # ---- contrato ResponseStore (Parte 2) ------------------------------------------------------------------
    _SECTION_FIELDS = {"generation_status", "iterations", "needs_human_review", "draft_content", "pending_items", "evaluation_results",
                       "evaluation_history", "generation_error"}

    def get_part2_input(self, ticket_id: int) -> dict:
        with self._session() as s:
            t = s.get(RfpTicket, ticket_id)
            if t is None:
                raise KeyError(ticket_id)
            sections = {r.department_id: {"department_id": r.department_id, "generation_status": r.generation_status,
                                          "iterations": r.iterations, "needs_human_review": r.needs_human_review,
                                          "draft_content": r.draft_content, "pending_items": r.pending_items,
                                          "evaluation_results": r.evaluation_results, "evaluation_history": r.evaluation_history}
                        for r in get_sections(s, ticket_id)}
            return {"status": t.status, "handoff": t.handoff, "processing_error": t.processing_error, "sections": sections}

    def begin_generation(self, ticket_id: int, departments: list[str], resume: bool) -> None:
        with self._session() as s:
            t = s.get(RfpTicket, ticket_id)
            t.status, t.processing_error, t.part3_handoff, t.response_completed_at = part2.STATUS_GENERATING, None, None, None
            t.current_node, t.heartbeat_at, t.updated_at = "generation:begin", _now(), _now()
            s.add(t)
            for row in get_sections(s, ticket_id):
                if row.department_id in departments:
                    row.generation_status, row.iterations, row.needs_human_review = part2.SECTION_PENDING, 0, False
                    row.draft_content, row.evaluation_results, row.evaluation_history = None, None, []
                    row.pending_items, row.generation_error = [], None
                    s.add(row)
            s.commit()

    def section_update(self, ticket_id: int, department_id: str, **fields) -> None:
        unknown = set(fields) - self._SECTION_FIELDS
        if unknown:
            raise ValueError(f"Campos de sección desconocidos: {sorted(unknown)}")
        with self._session() as s:
            row = s.exec(select(RfpDepartmentSection).where(RfpDepartmentSection.ticket_id == ticket_id,
                                                            RfpDepartmentSection.department_id == department_id)).first()
            for k, v in fields.items():
                setattr(row, k, v)
            s.add(row)
            s.commit()

    def mark_evaluating(self, ticket_id: int) -> None:
        with self._session() as s:
            t = s.get(RfpTicket, ticket_id)
            if t.status == part2.STATUS_GENERATING:
                t.status, t.updated_at = part2.STATUS_EVALUATING, _now()
                s.add(t)
                s.commit()

    def complete_generation(self, ticket_id: int, status: str, part3_handoff: dict) -> None:
        self._update(ticket_id, status=status, part3_handoff=part3_handoff, processing_error=None, response_completed_at=_now(),
                     current_node="generation:complete", heartbeat_at=_now())

    def fail_generation(self, ticket_id: int, message: str) -> None:
        self._update(ticket_id, processing_error=message[:2000])

    # ---- contrato ApprovalStore (Parte 3) ------------------------------------------------------------------
    def get_part3_input(self, ticket_id: int) -> dict:
        with self._session() as s:
            t = s.get(RfpTicket, ticket_id)
            if t is None:
                raise KeyError(ticket_id)
            sections = {}
            for r in get_sections(s, ticket_id):
                row = {"department_id": r.department_id, "key_aspects": r.key_aspects, "figures": r.figures or {}, "open_questions": r.open_questions,
                       "generation_status": r.generation_status, "iterations": r.iterations, "needs_human_review": bool(r.needs_human_review),
                       "draft_content": r.draft_content, "pending_items": r.pending_items, "evaluation_results": r.evaluation_results,
                       "evaluation_history": r.evaluation_history, "approval_status": r.approval_status, "approver": r.approver,
                       "approved_at": r.approved_at.isoformat() if r.approved_at else None, "approval_comment": r.approval_comment,
                       "approval_round": r.approval_round or 0, "approval_history": r.approval_history or [], "escalated": bool(r.escalated),
                       "approval_branch": r.approval_branch or part3.BRANCH_IDLE}
                sections[r.department_id] = row
            return {"status": t.status, "handoff": t.handoff, "part3_handoff": t.part3_handoff, "sections": sections, "ceo": t.ceo_approval,
                    "conflicts_log": t.conflicts_log or [], "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                    "processing_error": t.processing_error}

    def open_approval(self, ticket_id: int, ceo: dict) -> None:
        with self._session() as s:
            t = s.get(RfpTicket, ticket_id)
            t.status, t.processing_error, t.ceo_approval, t.conflicts_log = part3.STATUS_AWAITING, None, ceo, []
            t.completed_at, t.closing_claimed, t.current_node, t.heartbeat_at, t.updated_at = None, False, "approval:open", _now(), _now()
            s.add(t)
            s.exec(delete(RfpFinalDocument).where(RfpFinalDocument.ticket_id == ticket_id))
            for row in get_sections(s, ticket_id):
                row.approval_status, row.approver, row.approved_at = part3.APPROVAL_PENDING, None, None
                row.approval_comment, row.approval_round, row.approval_history = None, 0, []
                row.escalated, row.approval_branch = False, part3.BRANCH_IDLE
                s.add(row)
            s.commit()

    def approval_update(self, ticket_id: int, department_id: str, **fields) -> None:
        unknown = set(fields) - SECTION_FIELDS
        if unknown:
            raise ValueError(f"Campos de aprobación desconocidos: {sorted(unknown)}")
        if isinstance(fields.get("approved_at"), str):
            fields["approved_at"] = datetime.fromisoformat(fields["approved_at"])
        with self._session() as s:
            row = s.exec(select(RfpDepartmentSection).where(RfpDepartmentSection.ticket_id == ticket_id,
                                                            RfpDepartmentSection.department_id == department_id)).first()
            for k, v in fields.items():
                setattr(row, k, v)
            s.add(row)
            s.commit()

    def ticket_update(self, ticket_id: int, **fields) -> None:
        unknown = set(fields) - TICKET_FIELDS
        if unknown:
            raise ValueError(f"Campos de ticket desconocidos: {sorted(unknown)}")
        self._update(ticket_id, **fields)

    def end_work(self, ticket_id: int) -> None:
        self._update(ticket_id, current_node=None)

    def claim_close(self, ticket_id: int) -> bool:
        """Atómico en la base de datos: solo una petición gana el derecho a generar el documento final."""
        with self._session() as s:
            result = s.exec(update(RfpTicket).where(RfpTicket.ticket_id == ticket_id, RfpTicket.status == part3.STATUS_AWAITING,
                                                    RfpTicket.closing_claimed.is_not(True)).values(closing_claimed=True))
            s.commit()
            return result.rowcount == 1

    def save_final_document(self, ticket_id: int, document: dict) -> None:
        with self._session() as s:
            s.exec(delete(RfpFinalDocument).where(RfpFinalDocument.ticket_id == ticket_id))
            s.add(RfpFinalDocument(ticket_id=ticket_id, content=document["content"], sections=document["sections"],
                                   total_estimated_value=document["total_estimated_value"], compliance=document["compliance"],
                                   generated_at=datetime.fromisoformat(document["generated_at"])))
            s.commit()

    def complete_approval(self, ticket_id: int) -> None:
        self._update(ticket_id, status=part3.STATUS_DONE, completed_at=_now(), processing_error=None, current_node="approval:complete")

    def fail_approval(self, ticket_id: int, message: str) -> None:
        self._update(ticket_id, processing_error=message[:2000], closing_claimed=False)

    def record_event(self, ticket_id: int, event: dict) -> None:
        with self._session() as s:
            s.add(RfpTraceEvent(ticket_id=ticket_id, part=event["part"], agent=event["agent"], node=event["node"], thread_id=event.get("thread_id"),
                                input=event.get("input"), output=event.get("output"), ts=datetime.fromisoformat(event["ts"])))
            s.commit()

    def list_events(self, ticket_id: int) -> list[dict]:
        with self._session() as s:
            rows = s.exec(select(RfpTraceEvent).where(RfpTraceEvent.ticket_id == ticket_id).order_by(RfpTraceEvent.id)).all()
            return [{"seq": r.id, "ticket_id": r.ticket_id, "part": r.part, "agent": r.agent, "node": r.node, "thread_id": r.thread_id,
                     "input": r.input, "output": r.output, "ts": r.ts.isoformat()} for r in rows]


# ---- consultas / altas para las rutas ------------------------------------------------------------------------
def create_ticket(session: Session, *, raw_pdf_path: str, original_filename: str, uploaded_by: str | None) -> RfpTicket:
    ticket = RfpTicket(raw_pdf_path=raw_pdf_path, original_filename=original_filename, uploaded_by=uploaded_by,
                       status=STATUS_ANALYZING, heartbeat_at=_now(), current_node="uploaded")
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


def set_pdf_path(session: Session, ticket: RfpTicket, path: str) -> None:
    ticket.raw_pdf_path = path
    session.add(ticket)
    session.commit()


def list_tickets(session: Session) -> list[RfpTicket]:
    return list(session.exec(select(RfpTicket).order_by(RfpTicket.ticket_id.desc())).all())


def get_ticket(session: Session, ticket_id: int) -> RfpTicket | None:
    return session.get(RfpTicket, ticket_id)


def get_metadata(session: Session, ticket_id: int) -> RfpMetadata | None:
    return session.exec(select(RfpMetadata).where(RfpMetadata.ticket_id == ticket_id)).first()


def get_sections(session: Session, ticket_id: int) -> list[RfpDepartmentSection]:
    return list(session.exec(select(RfpDepartmentSection).where(RfpDepartmentSection.ticket_id == ticket_id)).all())


def get_final_document(session: Session, ticket_id: int) -> RfpFinalDocument | None:
    return session.exec(select(RfpFinalDocument).where(RfpFinalDocument.ticket_id == ticket_id)).first()
