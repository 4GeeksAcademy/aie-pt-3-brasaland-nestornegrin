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
    approved: int = 0  # Parte 3: secciones con el visto bueno de su responsable
    awaiting: int = 0  # Parte 3: secciones con una interrupción pendiente


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
    # --- Parte 3 ---
    approver: str | None = None
    approved_at: datetime | None = None
    approval_comment: str | None = None
    approval_round: int | None = None
    approval_history: list | None = None
    escalated: bool | None = None
    approval_branch: str | None = None
    review_packet: dict | None = None  # lo mínimo que el humano necesita ver para decidir (solo si hay una interrupción pendiente)


class ApprovalIn(BaseModel):
    action: str  # approve | reject | request_changes
    approver: str  # el responsable nombrado del departamento (BRIEFING §2.1) o, escalado, la dueña del ticket
    comment: str = ""
    figures: dict[str, str] = {}


class TraceEventOut(BaseModel):
    seq: int
    part: int
    agent: str
    node: str
    thread_id: str | None = None
    input: object | None = None
    output: object | None = None
    ts: str


class FinalDocumentOut(BaseModel):
    ticket_id: int
    content: str
    sections: list
    total_estimated_value: float | None
    compliance: dict
    generated_at: datetime


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
    # --- Parte 3 ---
    ceo_approval: dict | None = None
    ceo_packet: dict | None = None
    conflicts: list | None = None
    completed_at: datetime | None = None
    has_final_document: bool = False
