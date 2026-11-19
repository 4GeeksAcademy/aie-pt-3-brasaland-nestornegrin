"""Pub/sub en memoria del chat: un canal por sesión (`chat.<session_id>`).

El productor (el hilo que ejecuta el agente) publica en el canal y no sabe cuántas conexiones hay; cada conexión WebSocket está
suscrita con su PROPIA cola. Así una sesión con varios clientes (el encargado y un supervisor mirando) reparte los mismos eventos
con UNA sola ejecución del agente. Publicar no bloquea: la cola es de tamaño acotado y una conexión que no da abasto se cierra en
lugar de frenar al resto o perder eventos en silencio (al reconectar recupera el estado con `session_snapshot`).

Límite conocido: vive en el proceso. Con varios workers haría falta Redis pub/sub detrás de esta misma interfaz (`subscribe`/`publish`).
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

Event = dict[str, Any]  # {"event": nombre, "data": {...}}


def channel_for(session_id: str) -> str:
    return f"chat.{session_id}"


class Subscription:
    def __init__(self, channel: str, loop: asyncio.AbstractEventLoop, maxsize: int):
        self.channel = channel
        self.queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self.overflowed = False
        self._loop = loop

    def _put(self, event: Event) -> None:  # siempre en el hilo del bucle de eventos
        if self.overflowed:
            return
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self.overflowed = True

    def deliver(self, event: Event) -> None:
        self._loop.call_soon_threadsafe(self._put, event)


class ChatBroker:
    def __init__(self, queue_size: int = 1000):
        self._queue_size = queue_size
        self._subscribers: dict[str, set[Subscription]] = {}
        self._lock = threading.Lock()

    def subscribe(self, session_id: str) -> Subscription:
        subscription = Subscription(channel_for(session_id), asyncio.get_running_loop(), self._queue_size)
        with self._lock:
            self._subscribers.setdefault(subscription.channel, set()).add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        with self._lock:
            members = self._subscribers.get(subscription.channel)
            if members is not None:
                members.discard(subscription)
                if not members:
                    del self._subscribers[subscription.channel]

    def publish(self, session_id: str, event: str, data: dict[str, Any]) -> None:
        """Seguro desde cualquier hilo. Respeta el orden de publicación (call_soon_threadsafe es FIFO)."""
        message: Event = {"event": event, "data": {"session_id": session_id, **data}}
        with self._lock:
            members = list(self._subscribers.get(channel_for(session_id), ()))
        for subscription in members:
            subscription.deliver(message)

    def subscriber_count(self, session_id: str) -> int:
        with self._lock:
            return len(self._subscribers.get(channel_for(session_id), ()))
