"""Trazabilidad de punta a punta de una RFP (Hito 9 · Partes 1–3): qué agente hizo qué, con qué entrada, qué salida y cuándo.

Cada nodo de los tres grafos llama a `emit`; el almacén (PostgreSQL en producción) guarda los eventos en orden. La trazabilidad
NUNCA debe romper el flujo: un fallo al escribir un evento se registra en el log y se ignora.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)
HIDDEN_KEYS = {"markdown", "handoff", "payload", "part3_handoff"}  # voluminosos: se resumen por su tamaño
MAX_TEXT = 400


def summarize(value: Any, depth: int = 0) -> Any:
    """Versión acotada y serializable de un valor (los textos largos se recortan, las listas largas se cuentan)."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= MAX_TEXT else value[:MAX_TEXT] + f"… [{len(value)} caracteres]"
    if depth >= 3:
        return f"<{type(value).__name__}>"
    if isinstance(value, dict):
        return {str(k): (f"<{type(v).__name__} omitido>" if k in HIDDEN_KEYS else summarize(v, depth + 1)) for k, v in list(value.items())[:25]}
    if isinstance(value, (list, tuple, set)):
        items = [summarize(v, depth + 1) for v in list(value)[:8]]
        return items + [f"… +{len(value) - 8} más"] if len(value) > 8 else items
    return str(value)[:MAX_TEXT]


def emit(store: Any, ticket_id: int, *, part: int, agent: str, node: str, input: Any = None, output: Any = None,
         thread_id: str | None = None) -> dict:
    """Registra un evento y lo devuelve (para dejarlo también en el estado del grafo)."""
    event = {"ticket_id": ticket_id, "part": part, "agent": agent, "node": node, "thread_id": thread_id,
             "input": summarize(input), "output": summarize(output), "ts": datetime.now(timezone.utc).isoformat()}
    record = getattr(store, "record_event", None)
    if record is not None:
        try:
            record(ticket_id, event)
        except Exception:  # noqa: BLE001 - la trazabilidad no puede tumbar el flujo
            logger.exception("rfp_trace: no se pudo registrar el evento %s/%s del ticket %s", agent, node, ticket_id)
    return event
