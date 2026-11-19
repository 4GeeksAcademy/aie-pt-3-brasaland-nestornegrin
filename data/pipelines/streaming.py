"""Gancho de streaming del modelo de generación: un canal neutro entre `rag.complete()` y quien quiera ver los tokens.

`complete()` no sabe nada de WebSockets. Si hay un `StreamSink` activo en el contexto (contextvar) pide el texto en streaming
al proveedor, entrega cada fragmento al sink y, aun así, devuelve el texto completo como siempre. Sin sink el comportamiento
no cambia (una sola petición, sin streaming): la lógica del agente es la misma con y sin canal en vivo.

La cancelación es REAL: el sink lleva un `threading.Event`; `complete()` lo comprueba antes de llamar y en cada fragmento, y
al verlo activado cierra el stream del proveedor (deja de consumir tokens) y lanza `GenerationCancelled`, que atraviesa el grafo
y termina la corrida. No tiene nada que ver con `interrupt()` de LangGraph (pausa para humano en el grafo).
"""
from __future__ import annotations

import contextlib
import contextvars
import threading
from typing import Callable, Iterator


class GenerationCancelled(Exception):
    """El consumidor pidió abortar la generación en curso."""


class StreamSink:
    def __init__(self, on_delta: Callable[[str], None]):
        self.on_delta = on_delta
        self.cancelled = threading.Event()

    def cancel(self) -> None:
        self.cancelled.set()

    def check(self) -> None:
        if self.cancelled.is_set():
            raise GenerationCancelled()

    def emit(self, delta: str) -> None:
        self.check()
        if delta:
            self.on_delta(delta)


_current: contextvars.ContextVar[StreamSink | None] = contextvars.ContextVar("generation_stream_sink", default=None)


def current_sink() -> StreamSink | None:
    return _current.get()


@contextlib.contextmanager
def use_sink(sink: StreamSink) -> Iterator[StreamSink]:
    token = _current.set(sink)
    try:
        yield sink
    finally:
        _current.reset(token)
