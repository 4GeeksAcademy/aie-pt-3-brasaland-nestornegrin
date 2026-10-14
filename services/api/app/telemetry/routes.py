from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from sqlmodel import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.telemetry.allowlists import EVENT_ALLOWLISTS
from app.telemetry.models import TelemetryEvent, TelemetryReceipt
from app.telemetry.report import get_report
from app.telemetry.repository import insert_events

logger = logging.getLogger("telemetry")
# uvicorn solo configura sus propios loggers: sin esto los INFO de la app no salen por consola.
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     [telemetry] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

MAX_EVENTS_PER_BATCH = 500


def build_tags(event: TelemetryEvent) -> dict[str, Any] | None:
    """`properties` filtrado por la allowlist del evento (lo que se guarda en `tags`).

    Devuelve None si el evento no cumple el contrato de Fase 1
    (`docs/telemetry/event-schemas.json`): tipo desconocido o faltan propiedades
    obligatorias. Las claves fuera de la allowlist se descartan (nunca se guardan).
    """
    rule = EVENT_ALLOWLISTS.get(event.event_type)
    if rule is None:
        return None
    tags = {key: value for key, value in event.properties.items() if key in rule.allowed}
    if any(key not in tags for key in rule.required):
        return None
    return tags


def create_router() -> APIRouter:
    """Router de telemetría.

    `POST /telemetry/events` (ingesta) NO exige autenticación: los eventos de login fallido
    y errores ocurren antes de tener sesión y `sendBeacon` no puede enviar cabeceras.
    `GET /telemetry/report` (lectura) SÍ la exige: expone datos internos del sistema."""
    router = APIRouter(prefix="/telemetry", tags=["telemetry"])

    @router.post("/events", response_model=TelemetryReceipt)
    async def receive_events(request: Request, session: Session = Depends(get_db)) -> TelemetryReceipt:
        # 1) Envelope laxo: se lee el cuerpo en crudo (el frontend envía `text/plain`
        #    para que sendBeacon no necesite preflight de CORS) y NO se tipa como
        #    list[TelemetryEvent]: un evento inválido haría fallar (422) todo el lote.
        try:
            payload = json.loads(await request.body())
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="El cuerpo debe ser JSON")
        raw_events = payload.get("events") if isinstance(payload, dict) else None
        if not isinstance(raw_events, list):
            raise HTTPException(status_code=400, detail='El cuerpo debe tener la forma {"events": [...]}')
        if len(raw_events) > MAX_EVENTS_PER_BATCH:
            raise HTTPException(status_code=413, detail=f"Máximo {MAX_EVENTS_PER_BATCH} eventos por lote")

        # 2) Parseo por evento: los válidos van al bulk insert; los inválidos suman a `rejected`.
        rows: list[dict[str, Any]] = []
        rejected = 0
        for raw in raw_events:
            try:
                event = TelemetryEvent.model_validate(raw)
            except ValidationError:
                rejected += 1
                continue
            tags = build_tags(event)
            if tags is None:
                rejected += 1
                continue
            timestamp = event.timestamp if event.timestamp.tzinfo else event.timestamp.replace(tzinfo=timezone.utc)
            rows.append(
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "timestamp": timestamp,
                    "service": event.source,
                    "user_id": event.user_id,
                    "session_id": event.session_id,
                    "tags": tags,
                }
            )

        # 3) Una sola operación (una sentencia, una transacción) para todo el lote.
        stored = insert_events(session, rows)
        # Los ya guardados (mismo eventId, p. ej. un reintento) no se duplican y cuentan como rechazados.
        rejected += len(rows) - stored

        received = len(raw_events)
        logger.info("telemetry batch: received=%d stored=%d rejected=%d", received, stored, rejected)
        for row in rows:
            logger.info("telemetry event: %s", row["event_type"])
        return TelemetryReceipt(received=received, stored=stored, rejected=rejected)

    @router.get("/report", dependencies=[Depends(get_current_user)])
    def telemetry_report(
        response: Response,
        start_date: datetime | None = Query(default=None, description="ISO 8601, inclusivo. Por defecto: end_date − 7 días (UTC)."),
        end_date: datetime | None = Query(default=None, description="ISO 8601, exclusivo. Por defecto: ahora (UTC)."),
        session: Session = Depends(get_db),
    ) -> dict[str, Any]:
        """Reporte técnico: métricas operacionales calculadas por `analysis.py`.

        Este handler no calcula nada: el período se resuelve una vez, el pipeline de
        análisis hace el trabajo y el resultado se cachea 60 s por combinación de fechas.
        La cabecera `X-Cache` (HIT/MISS) indica si se recalculó.
        """
        report, from_cache = get_report(session, start_date, end_date)
        response.headers["X-Cache"] = "HIT" if from_cache else "MISS"
        return report

    return router
