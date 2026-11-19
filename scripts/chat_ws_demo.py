"""Comprobación manual del chat WebSocket SIN claves ni red externa: levanta la API real (uvicorn) con el router del chat, un proveedor
de LLM falso que «escribe» lento (80 ms por token) y el AgentService real, y se conecta por un WebSocket de verdad.

    PYTHONPATH=.:services/api:tests/chat uv run --project services/api python -m scripts.chat_ws_demo

Mide: tiempo hasta el primer token vs. respuesta completa, el aborto real al interrumpir (ningún token del primer intento tras
`generation_interrupted`), el parcial marcado `interrupted`, el turno nuevo y la rehidratación al reconectar con el mismo session_id.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("JWT_SECRET_KEY", "demo-secret-not-for-production")
os.environ["CHAT_DB_PATH"] = ":memory:"

import uvicorn  # noqa: E402
import websockets  # noqa: E402
from fastapi import FastAPI  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "chat"))
from chat_support import FakeProvider, FakeStream, install_provider, real_agent_service  # noqa: E402
from services.agent.chat.router import ChatUser, create_chat_router  # noqa: E402

PORT = 8765
SESSION = "chat_demo_0001"


class SlowStream(FakeStream):
    def __iter__(self):
        for chunk in super().__iter__():
            time.sleep(0.08)
            yield chunk


def script(question: str):
    if "Miami" in question:
        return SlowStream([w + " " for w in "Entendido, el local de Miami recibe al proveedor los martes por la mañana.".split()])
    return SlowStream([w + " " for w in "El proveedor de Chicago entrega los lunes y los jueves por la mañana temprano, antes de abrir.".split()])


class MonkeyPatch:  # el mínimo que necesita install_provider
    def setattr(self, obj, name, value):
        setattr(obj, name, value)


async def demo() -> None:
    uri = f"ws://127.0.0.1:{PORT}/agent/chat/ws?session_id={SESSION}&token=demo"
    t0 = time.time()
    async with websockets.connect(uri) as ws:
        assert json.loads(await ws.recv())["event"] == "session_snapshot"
        await ws.send(json.dumps({"event": "user_message", "data": {"text": "¿Cuándo entrega el proveedor de Chicago?"}}))
        first_token_at, seen = None, 0
        while seen < 4:
            event = json.loads(await ws.recv())
            if event["event"] == "token_chunk":
                first_token_at = first_token_at or time.time() - t0
                seen += 1
                print(f"  +{time.time() - t0:5.2f}s token_chunk #{event['data']['sequence']}: {event['data']['token']!r}")
        print(f"→ primer token a los {first_token_at:.2f}s (la respuesta completa tardaría ~{0.08 * 16:.1f}s)")
        t_interrupt = time.time()
        await ws.send(json.dumps({"event": "interrupt_requested", "data": {"new_input": "espera, pregunté por el local de Miami"}}))
        after_interrupt, interrupted_seen, text = [], False, ""
        while True:
            event = json.loads(await ws.recv())
            name = event["event"]
            print(f"  +{time.time() - t0:5.2f}s {name} {json.dumps(event['data'], ensure_ascii=False)[:90]}")
            if name == "generation_interrupted":
                interrupted_seen = True
                print(f"→ aborto confirmado {time.time() - t_interrupt:.3f}s después de pedirlo")
            elif name == "token_chunk" and interrupted_seen:
                after_interrupt.append(event)
            elif name == "generation_completed":
                break
    old_tokens_after_cut = [e for e in after_interrupt if "Chicago" in e["data"]["token"] or "lunes" in e["data"]["token"]]
    assert not old_tokens_after_cut, "llegaron tokens del primer intento tras generation_interrupted"
    print("→ ningún token del primer intento después de generation_interrupted ✔")
    async with websockets.connect(uri) as ws:  # reconexión con el mismo session_id
        snapshot = json.loads(await ws.recv())["data"]["messages"]
    for m in snapshot:
        print(f"  snapshot {m['message_id']} {m['role']:9} {m['status']:11} {m['text']!r}")
    assert [m["status"] for m in snapshot if m["role"] == "assistant"] == ["interrupted", "completed"]
    print("→ reconexión: historial rehidratado con el parcial `interrupted` y la respuesta nueva ✔")


def main() -> None:
    install_provider(MonkeyPatch(), FakeProvider(script))
    service = real_agent_service(Path(tempfile.mkdtemp()))
    app = FastAPI()
    app.include_router(create_chat_router(lambda token: ChatUser("1") if token == "demo" else None, lambda: service))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    try:
        asyncio.run(demo())
    finally:
        server.should_exit = True


if __name__ == "__main__":
    main()
