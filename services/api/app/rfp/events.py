"""Notificaciones en tiempo real de las RFPs (Server-Sent Events). Sin ninguna llamada a un modelo: es una capa de comunicación.

Contrato del canal `GET /rfp/events` (el mismo JWT que el resto de la API del backoffice):

    retry: 3000                                  <- espera sugerida al navegador antes de reconectar
    id: 17                                       <- ticket_id: sirve de `Last-Event-ID` al reconectar
    event: rfp_ticket_created                    <- evento NOMBRADO (nunca el `message` genérico)
    data: {"ticket_id": 17, "rfp_id": "RFP-00017", "status": "analizando", "requires_processing": true, ...}

    : keep-alive                                 <- frame de comentario periódico para que proxies/balanceadores no cierren

Diseño:
- Un `RfpEventBroker` por proceso reparte cada evento a una cola POR CONEXIÓN. Publicar es O(conexiones) en memoria y no toca
  la base de datos: 50 personas con el dashboard abierto son 50 colas pequeñas, no 50 consultas.
- La recuperación no necesita una tabla de eventos: el `id` del evento es el `ticket_id` (monótono) y los tickets YA están en
  PostgreSQL. Al reconectar con `Last-Event-ID: N`, el servidor reenvía los tickets con `ticket_id > N` y sigue en vivo.
- Si una conexión es tan lenta que su cola se llena, el servidor la CIERRA en lugar de descartar eventos en silencio: el cliente
  reconecta con `Last-Event-ID` y recupera lo que faltaba desde la base de datos.
- Límite conocido: el broker vive en el proceso. Con varios workers de uvicorn haría falta un bus compartido (Redis pub/sub o
  `LISTEN/NOTIFY` de PostgreSQL); la recuperación por `Last-Event-ID` ya cubre cualquier evento que otro worker haya publicado.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, Iterable

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from data.pipelines.rfp_intake.departments import STATUS_ANALYZING

EVENT_TICKET_CREATED = "rfp_ticket_created"
KEEPALIVE_FRAME = ": keep-alive\n\n"
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",  # ningún intermediario debe cachear ni transformar el flujo
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # nginx: no acumular el cuerpo antes de enviarlo
}


def keepalive_seconds() -> float:
    return float(os.environ.get("RFP_SSE_KEEPALIVE_SECONDS", "15"))


def retry_ms() -> int:
    return int(os.environ.get("RFP_SSE_RETRY_MS", "3000"))


def replay_limit() -> int:
    return int(os.environ.get("RFP_SSE_REPLAY_LIMIT", "500"))


@dataclass(frozen=True)
class RfpEvent:
    """Un evento del canal. `id` es el `ticket_id`: monótono, único y consultable en la base de datos."""
    event: str
    id: int
    data: dict = field(default_factory=dict)


def ticket_created_event(*, ticket_id: int, rfp_id: str | None, original_filename: str, created_at) -> RfpEvent:
    """Payload del evento `rfp_ticket_created` con los campos del Ticket del BRIEFING §2.3 (`ticket_id`, `rfp_id`, `status`,
    `created_at`). Describe el ticket AL REGISTRARSE: su estado inicial es `analizando` y requiere procesamiento."""
    return RfpEvent(
        event=EVENT_TICKET_CREATED,
        id=ticket_id,
        data={
            "ticket_id": ticket_id,
            "rfp_id": rfp_id or f"RFP-{ticket_id:05d}",  # la referencia real del documento llega al terminar el análisis
            "status": STATUS_ANALYZING,
            "requires_processing": True,
            "original_filename": original_filename,
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
        },
    )


def format_event(event: RfpEvent) -> str:
    """Un frame SSE. `json.dumps` sin saltos de línea: cada `data:` ocupa exactamente una línea."""
    return f"id: {event.id}\nevent: {event.event}\ndata: {json.dumps(event.data, ensure_ascii=False, separators=(',', ':'))}\n\n"


def parse_last_event_id(raw: str | None) -> int | None:
    """`Last-Event-ID` es entrada del cliente: solo se acepta un entero no negativo; cualquier otra cosa se ignora."""
    if raw is None:
        return None
    raw = raw.strip()
    return int(raw) if raw.isdigit() else None


class Subscription:
    """Cola de UNA conexión. `offer` solo se llama desde el bucle de eventos de esa conexión."""

    def __init__(self, loop: asyncio.AbstractEventLoop, size: int):
        self.loop = loop
        self.queue: asyncio.Queue[RfpEvent] = asyncio.Queue(maxsize=size)
        self.lagged = False  # la cola se llenó: se cierra la conexión y el cliente se recupera con Last-Event-ID

    def offer(self, event: RfpEvent) -> None:
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self.lagged = True


class RfpEventBroker:
    def __init__(self, queue_size: int = 100):
        self._queue_size = queue_size
        self._subs: set[Subscription] = set()
        self._lock = threading.Lock()

    @property
    def connections(self) -> int:
        return len(self._subs)

    def subscribe(self) -> Subscription:
        sub = Subscription(asyncio.get_running_loop(), self._queue_size)
        with self._lock:
            self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        with self._lock:
            self._subs.discard(sub)

    def publish(self, event: RfpEvent) -> None:
        """Seguro desde cualquier hilo: cada entrega se programa en el bucle de la conexión destinataria."""
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            try:
                sub.loop.call_soon_threadsafe(sub.offer, event)
            except RuntimeError:  # el bucle de esa conexión ya se cerró
                self.unsubscribe(sub)


async def event_stream(request: Request, broker: RfpEventBroker, load_after: Callable[[int], Iterable[RfpEvent]],
                       last_event_id: int | None) -> AsyncIterator[str]:
    """Genera los frames de UNA conexión: recuperación (si hay `Last-Event-ID`) y luego eventos en vivo.

    Se suscribe ANTES de leer la base de datos para no perder un ticket registrado justo entre la recuperación y el vivo;
    el posible duplicado se descarta por `id` (`sent`).
    """
    sub = broker.subscribe()
    sent: deque[int] = deque(maxlen=1000)
    sent_set: set[int] = set()

    def mark(event_id: int) -> bool:
        if event_id in sent_set:
            return False
        if len(sent) == sent.maxlen:
            sent_set.discard(sent[0])
        sent.append(event_id)
        sent_set.add(event_id)
        return True

    try:
        yield f"retry: {retry_ms()}\n\n"
        if last_event_id is not None:
            for event in await run_in_threadpool(lambda: list(load_after(last_event_id))):
                if mark(event.id):
                    yield format_event(event)
        while not sub.lagged:
            try:
                event = await asyncio.wait_for(sub.queue.get(), timeout=keepalive_seconds())
            except asyncio.TimeoutError:
                if await request.is_disconnected():
                    break
                yield KEEPALIVE_FRAME
                continue
            if mark(event.id):
                yield format_event(event)
    finally:
        broker.unsubscribe(sub)
