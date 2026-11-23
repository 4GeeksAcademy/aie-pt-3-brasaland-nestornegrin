from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class UploadAccepted(BaseModel):
    ticket_id: int
    status: str


class Progress(BaseModel):
    total: int
    passed: int
    needs_review: int
    working: int
    errors: int


class TicketSummary(BaseModel):
    ticket_id: int
    rfp_id: str | None
    status: str
    processing: str  # running | failed | stalled | idle  (derivado de heartbeat/error; ver routes.processing_state)
    original_filename: str
    client_name: str | None = None
    current_node: str | None = None
    progress: Progress | None = None  # Parte 2: secciones aprobadas / en revisión humana / en curso
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
    # --- Parte 2 ---
    generation_status: str | None = None
    iterations: int | None = None
    needs_human_review: bool | None = None
    draft_content: str | None = None
    pending_items: list | None = None
    evaluation_results: dict | None = None
    evaluation_history: list | None = None
    generation_error: str | None = None


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
    part3_handoff: dict | None = None
    response_completed_at: datetime | None = None
