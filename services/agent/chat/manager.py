"""Orquestación del chat en vivo: una generación por sesión, interrupción real y rehidratación.

Qué hace (y qué NO hace) cada pieza:

- El agente (`AgentService.run`) NO se modifica. Se ejecuta en un hilo con un `StreamSink` activo; `rag.complete()` entrega cada
  fragmento al sink (`data/pipelines/streaming.py`) y el manager lo convierte en eventos `token_chunk` publicados en el canal de la sesión.
- INTERRUMPIR = abortar el stream. Al llegar un mensaje mientras se genera, el manager, bajo el cerrojo de la sesión: (1) marca la generación
  como cancelada (a partir de ese instante ningún token suyo se publica ni se guarda), (2) cancela el sink para que `complete()` cierre el
  stream del proveedor, (3) deja el parcial guardado como `interrupted` y publica `generation_interrupted`, y (4) abre un turno NUEVO
  (otro `message_id`) con el texto recibido. El mensaje interrumpido nunca se borra ni se sobrescribe.
  Esto es independiente de `interrupt()` de LangGraph (HITL): allí el grafo se PAUSA y espera una decisión; aquí la corrida se ABORTA.
- Un solo cerrojo por sesión hace atómicos «guardar token + publicarlo» y «tomar snapshot + suscribirse»: quien se conecta (o reconecta)
  recibe un snapshot que incluye exactamente los tokens publicados antes de su suscripción y, después, solo los posteriores.
- Los guardrails validan la respuesta COMPLETA tras generarla. Si el texto final difiere del que ya se mostró se emite `message_corrected`
  (extensión del contrato, documentada) antes de `generation_completed`; si no se mostró nada (rechazos del guardrail de entrada) el
  texto final se emite en `token_chunk`s para que el cliente lo trate igual.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Callable

from data.pipelines.streaming import GenerationCancelled, StreamSink, use_sink

from .broker import ChatBroker, Subscription
from .extract import VisibleTextExtractor
from .store import (MESSAGE_COMPLETED, MESSAGE_FAILED, MESSAGE_INTERRUPTED, MESSAGE_STREAMING, SESSION_ACTIVE,
                    SESSION_INTERRUPTED, ChatStore)

logger = logging.getLogger(__name__)

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")  # el mismo formato que `conversation_id` del agente: session_id lo reutiliza
MAX_INPUT_LENGTH = 2000


class ChatError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Generation:
    session_id: str
    message_id: str
    sink: StreamSink
    extractor: VisibleTextExtractor = field(default_factory=VisibleTextExtractor)
    streamed: str = ""
    cancelled: bool = False


class ChatSessionManager:
    def __init__(self, store: ChatStore, broker: ChatBroker, service_factory: Callable[[], object]):
        self.store = store
        self.broker = broker
        self._service_factory = service_factory
        self._generations: dict[str, Generation] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    def _lock(self, session_id: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(session_id, threading.RLock())

    # ------------------------------------------------------------------ conexión
    def open_session(self, session_id: str, user_id: str, location_id: str | None) -> dict:
        """Crea la sesión si no existe (el primer cliente la fija a su `user_id`) y devuelve la existente si ya estaba."""
        with self._lock(session_id):
            return self.store.ensure_session(session_id, user_id, location_id)

    def attach(self, session_id: str) -> tuple[dict, Subscription]:
        """Snapshot + suscripción de forma atómica. Cierra como `interrupted` un mensaje que quedó «streaming» sin generación viva."""
        with self._lock(session_id):
            if session_id not in self._generations:
                for message_id in self.store.orphaned_streaming(session_id):
                    self.store.finish_message(message_id, MESSAGE_INTERRUPTED)
            subscription = self.broker.subscribe(session_id)
            snapshot = {"session_id": session_id, "messages": self.store.messages(session_id)}
            return snapshot, subscription

    def detach(self, subscription: Subscription) -> None:
        self.broker.unsubscribe(subscription)

    def is_generating(self, session_id: str) -> bool:
        return session_id in self._generations

    # ------------------------------------------------------------------ turnos del usuario
    def submit(self, session_id: str, text: str, user_id: str) -> None:
        text = (text or "").strip() if isinstance(text, str) else ""
        if not text:
            raise ChatError("empty_message", "El mensaje no puede estar vacío.")
        if len(text) > MAX_INPUT_LENGTH:
            raise ChatError("message_too_long", f"El mensaje supera los {MAX_INPUT_LENGTH} caracteres.")
        with self._lock(session_id):
            running = self._generations.get(session_id)
            if running is not None:
                self.broker.publish(session_id, "interrupt_requested", {"new_input": text})
                self._abort(running)
            self.store.add_message(session_id, "user", text)
            self.store.set_status(session_id, SESSION_ACTIVE)
            self.broker.publish(session_id, "user_message", {"text": text})
            message_id = self.store.add_message(session_id, "assistant", "", MESSAGE_STREAMING)
            generation = Generation(session_id, message_id, StreamSink(lambda _delta: None))
            generation.sink.on_delta = lambda delta, g=generation: self._on_delta(g, delta)
            self._generations[session_id] = generation
            threading.Thread(target=self._run, args=(generation, text, user_id), name=f"chat-{message_id}", daemon=True).start()

    def _abort(self, generation: Generation) -> None:
        """Con el cerrojo de la sesión tomado. Tras volver, de esta generación no sale ni un token más."""
        generation.cancelled = True
        generation.sink.cancel()
        self.store.finish_message(generation.message_id, MESSAGE_INTERRUPTED)  # el parcial mostrado se conserva tal cual
        self.store.set_status(generation.session_id, SESSION_INTERRUPTED)
        self._generations.pop(generation.session_id, None)
        self.broker.publish(generation.session_id, "generation_interrupted",
                            {"message_id": generation.message_id, "status": MESSAGE_INTERRUPTED})

    # ------------------------------------------------------------------ hilo de generación
    def _on_delta(self, generation: Generation, raw: str) -> None:
        visible = generation.extractor.feed(raw)
        if visible:
            self._emit_token(generation, visible)

    def _emit_token(self, generation: Generation, token: str) -> None:
        with self._lock(generation.session_id):
            if generation.cancelled:  # abortada: nada más sale, aunque el hilo viejo aún no se haya enterado
                return
            sequence = self.store.append_token(generation.message_id, token)
            generation.streamed += token
            self.broker.publish(generation.session_id, "token_chunk", {"token": token, "sequence": sequence})

    def _run(self, generation: Generation, question: str, user_id: str) -> None:
        sid = generation.session_id
        try:
            with use_sink(generation.sink):
                run = self._service_factory().run(question, conversation_id=sid, actor=user_id)
        except GenerationCancelled:
            return
        except Exception:  # noqa: BLE001 - un fallo del agente no debe tumbar la conexión
            if generation.cancelled:  # el abort llega envuelto en AgentExecutionError: no es un fallo
                return
            logger.exception("Falló la generación %s de la sesión %s", generation.message_id, sid)
            self._fail(generation)
            return
        self._complete(generation, run.answer)

    def _complete(self, generation: Generation, final: str) -> None:
        sid = generation.session_id
        if not generation.streamed.strip():
            for piece in re.findall(r"\S+\s*", final):  # nada se mostró (p. ej. rechazo del guardrail): se emite el texto final
                self._emit_token(generation, piece)
        with self._lock(sid):
            if generation.cancelled:
                return
            if final.strip() != generation.streamed.strip():
                self.store.finish_message(generation.message_id, MESSAGE_STREAMING, final)
                self.broker.publish(sid, "message_corrected", {"message_id": generation.message_id, "text": final})
            self.store.finish_message(generation.message_id, MESSAGE_COMPLETED)
            self._generations.pop(sid, None)
            self.broker.publish(sid, "generation_completed", {"message_id": generation.message_id})

    def _fail(self, generation: Generation) -> None:
        sid = generation.session_id
        with self._lock(sid):
            if generation.cancelled:
                return
            self.store.finish_message(generation.message_id, MESSAGE_FAILED)
            self._generations.pop(sid, None)
            self.broker.publish(sid, "generation_failed", {
                "message_id": generation.message_id, "status": MESSAGE_FAILED,
                "detail": "El agente no pudo responder en este momento. Inténtalo de nuevo."})

    def shutdown(self) -> None:
        for generation in list(self._generations.values()):
            with self._lock(generation.session_id):
                self._abort(generation)
