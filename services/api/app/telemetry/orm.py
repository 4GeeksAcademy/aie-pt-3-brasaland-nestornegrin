"""Tabla `telemetry_events` (Supabase/Postgres).

NO es una tabla CRUD: es solo de escritura. Los eventos son hechos inmutables,
por eso este módulo y el repositorio no ofrecen ningún UPDATE ni DELETE (y la
migración SQL añade un trigger que los bloquea también en la base de datos).

Columnas fijas (`event_type`, `timestamp`, `service`) sostienen las consultas
analíticas; `tags` (JSONB) guarda el `properties` del envelope —solo las claves
de la allowlist— sin necesidad de alterar el esquema al añadir eventos.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, JSON, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class TelemetryEventRecord(SQLModel, table=True):
    __tablename__ = "telemetry_events"
    __table_args__ = (
        Index("ix_telemetry_events_timestamp", "timestamp"),
        Index("ix_telemetry_events_event_type", "event_type"),
        # GIN: búsquedas dentro del JSONB (p. ej. tags @> '{"restaurant": "Brasaland Laureles"}').
        Index("ix_telemetry_events_tags", "tags", postgresql_using="gin"),
    )

    # BIGSERIAL en Postgres; INTEGER en SQLite (solo para los tests).
    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    )
    # `eventId` del envelope. UNIQUE: un reenvío (reintento del frontend) no duplica el hecho.
    event_id: UUID = Field(sa_column=Column(Uuid, nullable=False, unique=True))
    event_type: str = Field(sa_column=Column(String, nullable=False))
    timestamp: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    # `source` del envelope: backend | frontend | job.
    service: str = Field(sa_column=Column(String, nullable=False))
    user_id: str = Field(sa_column=Column(String, nullable=False))
    session_id: str = Field(sa_column=Column(String, nullable=False))
    # `properties` filtrado por la allowlist del evento.
    tags: dict[str, Any] = Field(sa_column=Column(JSON().with_variant(JSONB, "postgresql"), nullable=False))
