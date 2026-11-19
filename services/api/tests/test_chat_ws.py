"""WebSocket `/agent/chat/ws`: JWT (mismo que el backoffice), rechazo previo a cualquier evento de chat, `session_id` obligatorio,
propiedad de la sesión (espectador de solo lectura) y el recorrido completo cliente ↔ servidor ↔ agente."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tests" / "chat"))
from chat_support import FakeProvider, FakeStream, install_provider, real_agent_service  # noqa: E402

import app.main as main_module  # noqa: E402
from app.auth.security import create_access_token  # noqa: E402
from app.auth.ws import authenticate_ws_token  # noqa: E402
from services.agent.chat.router import create_chat_router  # noqa: E402

SESSION = "chat_0044"


def make_user(email: str, admin: bool = False) -> tuple[int, str]:
    user = main_module.user_repository.create(email, "hash")
    if admin:
        main_module.user_repository._database.update({"role": "admin"}, doc_ids=[user.id])
    return user.id, create_access_token(user.id)


@pytest.fixture
def client(monkeypatch, tmp_path):
    install_provider(monkeypatch, FakeProvider(lambda q: FakeStream(["Los ", "martes", "."])))
    app = FastAPI()
    app.include_router(create_chat_router(authenticate_ws_token, lambda: real_agent_service(tmp_path)))
    return TestClient(app)


def receive_until(ws, name: str) -> list[dict]:
    seen = []
    while True:
        event = ws.receive_json()
        seen.append(event)
        if event["event"] == name:
            return seen


def test_sin_token_ni_frame_de_auth_se_cierra_antes_de_cualquier_evento(client):
    with client.websocket_connect(f"/agent/chat/ws?session_id={SESSION}") as ws:
        ws.send_json({"event": "hola", "data": {}})
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 4401


def test_token_invalido_en_la_url_rechaza_el_handshake(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/agent/chat/ws?session_id={SESSION}&token=basura"):
            pass


def test_token_de_usuario_inexistente_se_rechaza(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/agent/chat/ws?session_id={SESSION}&token={create_access_token(9999)}"):
            pass


def test_session_id_es_obligatorio_y_con_formato_valido(client):
    _, token = make_user("a@x.com")
    for query in (f"token={token}", f"session_id=a&token={token}", f"session_id=con espacios!&token={token}"):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/agent/chat/ws?{query}"):
                pass


def test_primer_frame_de_auth_con_jwt_valido(client):
    _, token = make_user("a@x.com")
    with client.websocket_connect(f"/agent/chat/ws?session_id={SESSION}") as ws:
        ws.send_json({"event": "auth", "data": {"token": token}})
        first = ws.receive_json()
    assert first["event"] == "session_snapshot" and first["data"] == {"session_id": SESSION, "messages": []}


def test_primer_frame_de_auth_invalido_cierra(client):
    with client.websocket_connect(f"/agent/chat/ws?session_id={SESSION}") as ws:
        ws.send_json({"event": "auth", "data": {"token": "malo"}})
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 4401


def test_conversacion_completa_y_reconexion_con_el_mismo_session_id(client):
    _, token = make_user("a@x.com")
    url = f"/agent/chat/ws?session_id={SESSION}&token={token}&location_id=loc_miami"
    with client.websocket_connect(url) as ws:
        assert ws.receive_json()["event"] == "session_snapshot"
        ws.send_json({"event": "user_message", "data": {"text": "¿Qué día entrega Miami?"}})
        events = receive_until(ws, "generation_completed")
    assert [e["event"] for e in events] == ["user_message", "token_chunk", "token_chunk", "token_chunk", "generation_completed"]
    assert events[1]["data"] == {"session_id": SESSION, "token": "Los ", "sequence": 1}
    with client.websocket_connect(url) as ws:  # reconexión: el historial vuelve en el snapshot, no un chat vacío
        snapshot = ws.receive_json()
    assert snapshot["event"] == "session_snapshot"
    assert [(m["role"], m["text"]) for m in snapshot["data"]["messages"]] == [("user", "¿Qué día entrega Miami?"), ("assistant", "Los martes.")]


def test_otro_usuario_no_puede_entrar_a_una_sesion_ajena(client):
    _, owner = make_user("a@x.com")
    _, other = make_user("b@x.com")
    with client.websocket_connect(f"/agent/chat/ws?session_id={SESSION}&token={owner}") as ws:
        ws.receive_json()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/agent/chat/ws?session_id={SESSION}&token={other}"):
            pass


def test_el_administrador_entra_como_espectador_de_solo_lectura(client):
    _, owner = make_user("a@x.com")
    _, admin = make_user("admin@x.com", admin=True)
    with client.websocket_connect(f"/agent/chat/ws?session_id={SESSION}&token={owner}") as ws:
        ws.receive_json()
    with client.websocket_connect(f"/agent/chat/ws?session_id={SESSION}&token={admin}") as ws:
        assert ws.receive_json()["event"] == "session_snapshot"
        ws.send_json({"event": "user_message", "data": {"text": "intruso"}})
        assert ws.receive_json()["data"]["code"] == "read_only"


def test_frames_invalidos_y_ping(client):
    _, token = make_user("a@x.com")
    with client.websocket_connect(f"/agent/chat/ws?session_id={SESSION}&token={token}") as ws:
        ws.receive_json()
        ws.send_text("no es json")
        assert ws.receive_json()["data"]["code"] == "invalid_frame"
        ws.send_json({"event": "inventado", "data": {}})
        assert ws.receive_json()["data"]["code"] == "unknown_event"
        ws.send_json({"event": "user_message", "data": {"text": "   "}})
        assert ws.receive_json()["data"]["code"] == "empty_message"
        ws.send_json({"event": "ping"})
        assert ws.receive_json()["event"] == "pong"
