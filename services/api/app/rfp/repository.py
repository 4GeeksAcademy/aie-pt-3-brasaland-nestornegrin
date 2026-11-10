"""Implementación PostgreSQL (SQLModel) del contrato `RfpStore` del pipeline + consultas para la API.

Cada operación abre su PROPIA sesión corta: el pipeline corre en un hilo de fondo (y los workers en paralelo), así que no se
comparte la sesión de la petición HTTP. `complete` escribe secciones + handoff + estado en UNA transacción: o queda todo o nada.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import delete
from sqlmodel import Session, select

from data.pipelines.rfp_intake.departments import STATUS_ANALYZING, STATUS_COMPLETE, STATUS_DISCARDED

from .models import RfpDepartmentSection, RfpMetadata, RfpTicket


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
