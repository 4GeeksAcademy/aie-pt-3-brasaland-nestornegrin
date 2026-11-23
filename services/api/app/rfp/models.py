"""Tablas SQLModel de la recepción de RFPs (Hito 9 · Parte 1) en PostgreSQL/Supabase.

Tres tablas: el ticket (estado y trazabilidad del pipeline), los metadatos de la RFP (incluye métricas de legibilidad) y una
sección por departamento activo. Las columnas de las Partes 2 y 3 (`draft_content`, `evaluation_results`, `approval_status`,
`approver`, `approved_at`) ya existen y son opcionales: `create_all` NO migra tablas existentes, así que se crean ahora.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RfpTicket(SQLModel, table=True):
    __tablename__ = "rfp_tickets"

    ticket_id: int | None = Field(default=None, primary_key=True)
    rfp_id: str | None = Field(default=None, index=True)  # referencia del documento o RFP-{ticket_id:05d}
    status: str = Field(default="analizando", index=True)  # analizando | descartado | analisis_completo (Parte 1)
    raw_pdf_path: str
    original_filename: str
    markdown: str | None = Field(default=None, sa_column=Column(Text))
    classification: dict | None = Field(default=None, sa_column=Column(JSON))
    discard_reason: str | None = None
    # Trazabilidad del trabajo en segundo plano: la base de datos, no la memoria del proceso, es la verdad.
    current_node: str | None = None
    heartbeat_at: datetime | None = None
    processing_error: str | None = None
    attempts: int = 0
    handoff: dict | None = Field(default=None, sa_column=Column(JSON))  # contrato hacia la Parte 2
    summary: dict | None = Field(default=None, sa_column=Column(JSON))  # resumen para Ventas
    uploaded_by: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class RfpMetadata(SQLModel, table=True):
    __tablename__ = "rfp_metadata"

    id: int | None = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="rfp_tickets.ticket_id", unique=True, index=True)
    reference: str | None = None
    client_name: str | None = None
    location: str | None = None
    service_type: str | None = None
    scope: str | None = None
    deadline: str | None = None
    deadline_iso: str | None = None
    budget_range: str | None = None
    budget_usd_min: float | None = None
    budget_usd_max: float | None = None
    departments_needed: list = Field(default_factory=list, sa_column=Column(JSON))
    open_questions: list = Field(default_factory=list, sa_column=Column(JSON))
    readability: dict = Field(default_factory=dict, sa_column=Column(JSON))


class RfpDepartmentSection(SQLModel, table=True):
    __tablename__ = "rfp_department_sections"

    id: int | None = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="rfp_tickets.ticket_id", index=True)
    department_id: str = Field(index=True)
    reason: str | None = None
    key_aspects: list = Field(default_factory=list, sa_column=Column(JSON))
    asks: list = Field(default_factory=list, sa_column=Column(JSON))
    figures: dict = Field(default_factory=dict, sa_column=Column(JSON))
    open_questions: list = Field(default_factory=list, sa_column=Column(JSON))
    excerpts: list = Field(default_factory=list, sa_column=Column(JSON))
    # --- Partes 2 y 3 (vacías en la Parte 1) ---
    draft_content: str | None = Field(default=None, sa_column=Column(Text))
    evaluation_results: dict | None = Field(default=None, sa_column=Column(JSON))
    approval_status: str = "pendiente"  # pendiente | aprobado | rechazado
    approver: str | None = None
    approved_at: datetime | None = None
