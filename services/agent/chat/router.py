"""WebSocket del chat del Manager support agent: `ws://<api>/agent/chat/ws?session_id=chat_0044&token=<JWT>`.

Handshake
- `session_id` es obligatorio (patrón `[A-Za-z0-9_-]{8,64}`) y es también el `conversation_id` que recibe el agente. Opcional: `location_id`.
- Autenticación con el MISMO JWT que el resto de la API: `?token=<JWT>` o, si no viene en la URL, un primer frame
  `{"event":"auth","data":{"token":"<JWT>"}}` (5 s). Sin token válido la conexión se cierra (4401) ANTES de enviar ningún evento de chat;
  con `?token=` inválido ni siquiera se completa el handshake.
- La primera sesión con un `session_id` queda ligada a su `user_id`. Otro usuario solo puede entrar si es administrador, y como espectador:
  recibe los mismos eventos (supervisor mirando en directo) pero no puede escribir (`read_only`).

Eventos del servidor: `session_snapshot`, `user_message`, `token_chunk`, `interrupt_requested`, `generation_interrupted`,
`generation_completed` (contrato del BRIEFING) y, como extensión documentada, `message_corrected`, `generation_failed` y `error`.
Eventos del cliente: `user_message` {text} o `interrupt_requested` {new_input} (equivalentes: si se está generando, se interrumpe), `ping`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .broker import ChatBroker
from .manager import SESSION_ID_PATTERN, ChatError, ChatSessionManager
from .store import ChatStore

logger = logging.getLogger(__name__)

CLOSE_BAD_REQUEST, CLOSE_UNAUTHORIZED, CLOSE_FORBIDDEN, CLOSE_TOO_SLOW = 4400, 4401, 4403, 1013
AUTH_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class ChatUser:
    user_id: str
    is_admin: bool = False


Authenticator = Callable[[str], "ChatUser | None"]


def create_chat_router(authenticate: Authenticator, service_factory: Callable[[], object], *, manager: ChatSessionManager | None = None,
                       store_path: str = ":memory:", prefix: str = "/agent") -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["agent-chat"])
    chat = manager or ChatSessionManager(ChatStore(store_path), ChatBroker(), service_factory)
    router.chat_manager = chat  # type: ignore[attr-defined]  # para las pruebas y para cerrar generaciones al apagar

    @router.websocket("/chat/ws")
    async def chat_socket(websocket: WebSocket) -> None:
        session_id = websocket.query_params.get("session_id", "")
        location_id = websocket.query_params.get("location_id") or None
        token = websocket.query_params.get("token")
        accepted = False

        async def reject(code: int) -> None:
            await websocket.close(code=code)

        user = authenticate(token) if token else None
        if token and user is None:
            return await reject(CLOSE_UNAUTHORIZED)  # antes de aceptar: el handshake responde 403, no se envía nada
        if not SESSION_ID_PATTERN.match(session_id):
            return await reject(CLOSE_BAD_REQUEST)
        if not token:  # primer frame de autenticación
            await websocket.accept()
            accepted = True
            try:
                frame = json.loads(await asyncio.wait_for(websocket.receive_text(), AUTH_TIMEOUT_SECONDS))
                candidate = frame["data"]["token"] if frame.get("event") == "auth" else None
                user = authenticate(candidate) if isinstance(candidate, str) else None
            except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, KeyError, TypeError):
                user = None
            if user is None:
                return await reject(CLOSE_UNAUTHORIZED)
        existing = chat.store.get_session(session_id)
        if existing is not None and existing["user_id"] != user.user_id and not user.is_admin:
            return await reject(CLOSE_FORBIDDEN)
        if not accepted:
            await websocket.accept()

        session = chat.open_session(session_id, user.user_id, location_id)
        read_only = session["user_id"] != user.user_id
        snapshot, subscription = chat.attach(session_id)
        try:
            await websocket.send_json({"event": "session_snapshot", "data": snapshot})

            async def pump_out() -> None:
                while True:
                    try:
                        event = await asyncio.wait_for(subscription.queue.get(), 1.0)
                    except asyncio.TimeoutError:
                        if subscription.overflowed:
                            return await websocket.close(code=CLOSE_TOO_SLOW)  # el cliente reconecta y se rehidrata
                        continue
                    await websocket.send_json(event)

            def reply_error(code: str, message: str) -> None:  # la cola es de ESTA conexión: el error no llega a los demás
                subscription._put({"event": "error", "data": {"session_id": session_id, "code": code, "message": message}})

            async def pump_in() -> None:
                while True:
                    raw = await websocket.receive_text()
                    try:
                        frame = json.loads(raw)
                        event, data = frame["event"], frame.get("data") or {}
                    except (ValueError, KeyError, TypeError):
                        reply_error("invalid_frame", "Frame no válido: se espera {\"event\": ..., \"data\": {...}}.")
                        continue
                    if event == "ping":
                        subscription._put({"event": "pong", "data": {"session_id": session_id}})
                    elif event in ("user_message", "interrupt_requested"):
                        if read_only:
                            reply_error("read_only", "Solo el encargado de la sesión puede escribir.")
                            continue
                        text = data.get("text") if event == "user_message" else data.get("new_input")
                        try:
                            chat.submit(session_id, text, user.user_id)
                        except ChatError as error:
                            reply_error(error.code, error.message)
                    else:
                        reply_error("unknown_event", f"Evento no soportado: {event!r}.")

            tasks = [asyncio.create_task(pump_out()), asyncio.create_task(pump_in())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                task.exception()  # consume la excepción (WebSocketDisconnect es el cierre normal)
        except WebSocketDisconnect:
            pass
        finally:
            chat.detach(subscription)  # la generación en curso NO se corta al desconectar: sigue guardándose para la rehidratación

    return router
