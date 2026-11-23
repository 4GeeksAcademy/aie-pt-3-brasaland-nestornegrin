"""Modelos Pydantic del sobre de evento (envelope) definido en
docs/telemetry/event-schemas.json (`definitions.envelope`).

`TelemetryEvent` valida solo el sobre. Las `properties` de cada tipo de evento
se validan contra su allowlist en el cliente; el stub las acepta tal cual para
que este mismo modelo se reutilice sin cambios cuando se persista (Fase 3).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TelemetryEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # Camel case en el sobre, snake_case solo en `event_type` (así lo fija el plan).
    event_id: UUID = Field(alias="eventId")
    timestamp: datetime
    session_id: str = Field(alias="sessionId", min_length=1)
    user_id: str = Field(alias="userId", min_length=1)
    event_type: str = Field(min_length=1, pattern=r"^[a-z]+(_[a-z]+)+$")
    schema_version: str = Field(alias="schemaVersion", pattern=r"^\d+\.\d+\.\d+$")
    request_id: UUID = Field(alias="requestId")
    source: Literal["backend", "frontend", "job"] = "frontend"
    properties: dict[str, Any] = Field(default_factory=dict)


class TelemetryBatch(BaseModel):
    events: list[TelemetryEvent] = Field(max_length=500)


class TelemetryReceipt(BaseModel):
    received: int
