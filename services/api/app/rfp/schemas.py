from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class UploadAccepted(BaseModel):
    ticket_id: int
    status: str


class TicketSummary(BaseModel):
    ticket_id: int
    rfp_id: str | None
    status: str
    processing: str  # running | failed | stalled | idle  (derivado de heartbeat/error; ver routes.processing_state)
    original_filename: str
    client_name: str | None = None
    current_node: str | None = None
    created_at: datetime
    updated_at: datetime


class SectionOut(BaseModel):
    department_id: str
    department: str
    owner: str
    reason: str | None
    key_aspects: list
    asks: list
    figures: dict
    open_questions: list
    excerpts: list
    approval_status: str


class TicketDetail(TicketSummary):
    discard_reason: str | None
    processing_error: str | None
    attempts: int
    classification: dict | None
    metadata: dict | None
    readability: dict | None
    sections: list[SectionOut]
    summary: dict | None
    handoff: dict | None
