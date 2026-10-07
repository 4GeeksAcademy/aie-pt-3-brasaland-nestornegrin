from __future__ import annotations

import logging

from fastapi import APIRouter

from app.telemetry.models import TelemetryBatch, TelemetryReceipt

logger = logging.getLogger("telemetry")


def create_router() -> APIRouter:
    """Router de telemetría. Sin autenticación: el sondeo de eventos de login
    fallido y errores ocurre antes de tener sesión y `sendBeacon` no puede
    enviar cabeceras personalizadas."""
    router = APIRouter(prefix="/telemetry", tags=["telemetry"])

    @router.post("/events", response_model=TelemetryReceipt)
    def receive_events(batch: TelemetryBatch) -> TelemetryReceipt:
        logger.info("telemetry batch received: %d events", len(batch.events))
        for event in batch.events:
            logger.info("telemetry event: %s", event.event_type)
        return TelemetryReceipt(received=len(batch.events))

    return router
