"""Notificaciones en tiempo real de las RFPs (Server-Sent Events). Sin ninguna llamada a un modelo: es una capa de comunicación.

Contrato del canal `GET /rfp/events` (el mismo JWT que el resto de la API del backoffice):

    retry: 3000                                  <- espera sugerida al navegador antes de reconectar
    id: 1795012345678901                         <- instante del aviso (µs desde 1970): sirve de `Last-Event-ID` al reconectar
    event: rfp_ticket_created                    <- evento NOMBRADO (nunca el `message` genérico)
    data: {"ticket_id":17,"rfp_id":"RFP-2026-017","client_name":"Andes Tech","location":"Medellín","service_type":"recurring_catering","status":"analyzing","created_at":"..."}

    : keep-alive                                 <- frame de comentario periódico para que proxies/balanceadores no cierren

Cuándo se dispara (BRIEFING §2): cuando el documento ya fue clasificado como RFP válida, el flujo lo está procesando (`analyzing` en el contrato; `analizando` en el sistema interno)
y sus metadatos están guardados. Un documento descartado NO genera aviso. Se anuncia una sola vez por ticket (`announced_at`).

Diseño:
- Un `RfpEventBroker` por proceso reparte cada evento a una cola POR CONEXIÓN. Publicar es O(conexiones) en memoria y no toca
  la base de datos: 50 personas con el dashboard abierto son 50 colas pequeñas, no 50 consultas.
- La recuperación no necesita una tabla de eventos: el `id` es el instante `announced_at` (monótono, ya persistido en el ticket).
  Al reconectar con `Last-Event-ID: N`, el servidor reenvía los tickets anunciados después de N y sigue en vivo. El `ticket_id` NO sirve
  de id: los tickets se clasifican en orden distinto al de subida, y un ticket antiguo puede anunciarse después de uno más nuevo.
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
from datetime import datetime, timedelta, timezone
from collections import deque
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, Iterable

from fastapi import Request
from starlette.concurrency import run_in_threadpool

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
    """Un evento del canal. `id` es el instante del aviso (`event_id_of`): monótono y consultable en la base de datos."""
    event: str
    id: int
    data: dict = field(default_factory=dict)


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# El BRIEFING define el enum de `status` en inglés. El sistema interno (base de datos, API REST, UI) sigue en español, así que el
# contrato SSE traduce EN EL BORDE: nada interno cambia. `needs_human_review` no tiene equivalente en el BRIEFING: es una revisión
# humana dentro de la evaluación, así que se publica como `under_evaluation`.
BRIEFING_STATUS = {
    "analizando": "analyzing",
    "analisis_completo": "intake_complete",
    "generando_borrador": "drafting",
    "en_evaluación": "under_evaluation",
    "needs_human_review": "under_evaluation",
    "esperando_aprobación": "waiting_for_approval",
    "terminado": "done",
    "descartado": "discarded",
}


def briefing_status(internal_status: str) -> str:
    """Estado interno (español) -> enum del BRIEFING (inglés). Un estado desconocido falla en voz alta, no se inventa."""
    return BRIEFING_STATUS[internal_status]


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


def event_id_of(announced_at: datetime) -> int:
    """`id` SSE: microsegundos desde 1970 del instante del aviso (entero, estrictamente creciente en la práctica)."""
    return (_utc(announced_at) - _EPOCH) // timedelta(microseconds=1)


def announced_after(event_id: int) -> datetime:
    """Inverso de `event_id_of`, en UTC sin zona (como se guarda `announced_at`)."""
    return (_EPOCH + timedelta(microseconds=event_id)).replace(tzinfo=None)


def _iso(moment) -> str | None:
    return moment.isoformat() if hasattr(moment, "isoformat") else (None if moment is None else str(moment))


def ticket_created_event(*, ticket_id: int, rfp_id: str | None, client_name: str | None, location: str | None, service_type: str | None,
                         status: str, created_at, announced_at: datetime) -> RfpEvent:
    """Payload PLANO de `rfp_ticket_created` con los campos del BRIEFING (`ticket_id`, `rfp_id`, `client_name`, `location`,
    `service_type`, `status`, `created_at`). `status` es el estado INTERNO (`analizando`) y sale traducido al enum del BRIEFING."""
    return RfpEvent(
        event=EVENT_TICKET_CREATED,
        id=event_id_of(announced_at),
        data={"ticket_id": ticket_id, "rfp_id": rfp_id, "client_name": client_name, "location": location, "service_type": service_type,
              "status": briefing_status(status), "created_at": _iso(created_at)},
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
