from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.telemetry.models import TelemetryBatch, TelemetryReceipt

logger = logging.getLogger("telemetry")
# uvicorn solo configura sus propios loggers: sin esto los INFO de la app no salen por consola.
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     [telemetry] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def create_router() -> APIRouter:
    """Router de telemetría. Sin autenticación: el sondeo de eventos de login
    fallido y errores ocurre antes de tener sesión y `sendBeacon` no puede
    enviar cabeceras personalizadas."""
    router = APIRouter(prefix="/telemetry", tags=["telemetry"])

    @router.post("/events", response_model=TelemetryReceipt)
    async def receive_events(request: Request) -> TelemetryReceipt:
        # Se lee el cuerpo en crudo y se valida con el modelo, sin exigir
        # `Content-Type: application/json`: el frontend envía `text/plain`
        # (cabecera "simple" de CORS) para que `sendBeacon` al cerrar la
        # pestaña no necesite preflight, que el navegador cancela al descargar la página.
        try:
            batch = TelemetryBatch.model_validate_json(await request.body())
        except ValidationError as error:
            raise RequestValidationError(error.errors()) from error
        logger.info("telemetry batch received: %d events", len(batch.events))
        for event in batch.events:
            logger.info("telemetry event: %s", event.event_type)
        return TelemetryReceipt(received=len(batch.events))

    return router
