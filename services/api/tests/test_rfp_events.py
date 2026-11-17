"""Canal SSE de las RFPs (`GET /rfp/events`): headers, framing de red (`event:` nombrado + `data:` JSON), JWT, keep-alive,
recuperación con `Last-Event-ID` y sin duplicados.

TestClient no sirve para streams infinitos (espera a que termine la respuesta), así que el endpoint se prueba a nivel ASGI: se
invoca la aplicación con un `receive`/`send` propios y se leen los frames tal y como los vería el navegador.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tests" / "pipelines"))
from rfp_support import PDF_FORMAL, PDF_INVALID, ScriptedRfpModel  # noqa: E402

import app.main as main_module  # noqa: E402
from app.auth.dependencies import get_current_user  # noqa: E402
from app.database import get_db  # noqa: E402
from app.rfp import models  # noqa: E402,F401
from app.rfp import repository  # noqa: E402
from app.rfp.events import RfpEventBroker, event_id_of, format_event, parse_last_event_id, ticket_created_event  # noqa: E402
from app.rfp.repository import SqlRfpStore  # noqa: E402
from app.rfp.routes import create_router  # noqa: E402


# ---- arnés ASGI: lee la respuesta en streaming como lo haría un navegador ----------------------------------
class AsgiStream:
    def __init__(self, app, path: str = "/rfp/events", headers: dict[str, str] | None = None):
        self.app = app
        self.scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1", "method": "GET",
                      "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
                      "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
                      "client": ("127.0.0.1", 5000), "server": ("testserver", 80)}
        self.status: int | None = None
        self.headers: dict[str, str] = {}
        self.closed = False
        self._messages: asyncio.Queue = asyncio.Queue()
        self._disconnect = asyncio.Event()
        self._sent_request = False
        self._buffer = ""
        self._task: asyncio.Task | None = None

    async def _receive(self):
        if not self._sent_request:
            self._sent_request = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await self._disconnect.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message):
        await self._messages.put(message)

    async def __aenter__(self):
        self._task = asyncio.create_task(self.app(self.scope, self._receive, self._send))
        start = await asyncio.wait_for(self._messages.get(), 3)
        assert start["type"] == "http.response.start"
        self.status = start["status"]
        self.headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
        return self

    async def __aexit__(self, *exc):
        self._disconnect.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task

    async def frame(self, timeout: float = 3.0) -> str:
        """Siguiente frame SSE completo (hasta la línea en blanco). `TimeoutError` si no llega nada; `EOFError` si el servidor cerró."""
        while "\n\n" not in self._buffer:
            if self.closed:
                raise EOFError("el servidor cerró el stream")
            message = await asyncio.wait_for(self._messages.get(), timeout)
            if message["type"] == "http.response.body":
                self._buffer += message.get("body", b"").decode()
                self.closed = not message.get("more_body", False)
        head, _, self._buffer = self._buffer.partition("\n\n")
        return head


def parse_frame(raw: str) -> dict:
    out: dict = {}
    for line in raw.splitlines():
        field, _, value = line.partition(": ")
        out[field] = value
    return out


# ---- fixtures ------------------------------------------------------------------------------------------------
@pytest.fixture
def sse(tmp_path, monkeypatch):
    monkeypatch.setenv("RFP_RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("RFP_AUTO_GENERATE", "0")
    monkeypatch.setenv("RFP_AUTO_REVIEW", "0")
    engine = create_engine(f"sqlite:///{tmp_path / 'rfp.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    broker = RfpEventBroker()
    app = FastAPI()
    app.include_router(create_router(store_factory=lambda: SqlRfpStore(lambda: Session(engine)), llm=ScriptedRfpModel(), broker=broker))
    app.dependency_overrides[get_current_user] = lambda: {"email": "camila@brasaland.test"}
    app.dependency_overrides[get_db] = lambda: Session(engine)
    return SimpleNamespace(app=app, client=TestClient(app), broker=broker, engine=engine)


def register_rfp(client: TestClient) -> int:
    response = client.post("/rfp/tickets", files={"file": (PDF_FORMAL.name, PDF_FORMAL.read_bytes(), "application/pdf")})
    assert response.status_code == 202, response.text
    return response.json()["ticket_id"]


async def register_rfp_async(client: TestClient) -> int:
    return await asyncio.to_thread(register_rfp, client)


def event_for(sse, ticket_id: int):
    """El evento tal y como lo publicó (o lo recuperaría) el servidor para ese ticket ya anunciado."""
    row = SqlRfpStore(lambda: Session(sse.engine))._announcement(ticket_id)
    assert row is not None, f"el ticket {ticket_id} no fue anunciado"
    return ticket_created_event(**row)


def upload_pdf(client: TestClient, pdf) -> int:
    response = client.post("/rfp/tickets", files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")})
    assert response.status_code == 202, response.text
    return response.json()["ticket_id"]


BRIEFING_FIELDS = {"ticket_id", "rfp_id", "client_name", "location", "service_type", "status", "created_at"}


# ---- headers y formato en el cable ------------------------------------------------------------------------------
def test_stream_headers_are_event_stream_without_cache_and_framing_is_named_event_with_json_data(sse):
    async def scenario():
        async with AsgiStream(sse.app) as stream:
            assert stream.status == 200
            assert stream.headers["content-type"] == "text/event-stream"  # exacto, sin «; charset»
            assert "no-cache" in stream.headers["cache-control"]
            assert stream.headers["x-accel-buffering"] == "no"
            assert (await stream.frame()) == "retry: 3000"
            ticket_id = await register_rfp_async(sse.client)
            raw = await stream.frame()
            assert raw.splitlines()[0] == f"id: {event_for(sse, ticket_id).id}"
            assert raw.splitlines()[1] == "event: rfp_ticket_created"  # evento nombrado, no `message`
            assert raw.splitlines()[2].startswith("data: {") and len(raw.splitlines()) == 3  # JSON en UNA línea
            data = json.loads(parse_frame(raw)["data"])
            assert data["ticket_id"] == ticket_id == 1
            assert set(data) == BRIEFING_FIELDS  # payload PLANO: solo los campos del BRIEFING, sin sobre {"event","data"}
            assert data["status"] == "analizando"  # mismo nombre de estado que usa todo el sistema
            assert data["rfp_id"] and data["client_name"] and data["location"] and data["service_type"]  # metadatos ya extraídos
            assert data["created_at"].startswith("20")  # ISO 8601

    asyncio.run(scenario())


def test_the_event_is_a_ticket_event_and_not_a_generic_message_for_every_new_ticket(sse):
    async def scenario():
        async with AsgiStream(sse.app) as stream:
            await stream.frame()  # retry
            ids = [await register_rfp_async(sse.client) for _ in range(2)]
            frames = [parse_frame(await stream.frame()) for _ in ids]
            assert [json.loads(f["data"])["ticket_id"] for f in frames] == ids
            assert int(frames[0]["id"]) < int(frames[1]["id"])  # el id crece con cada aviso
            assert {f["event"] for f in frames} == {"rfp_ticket_created"}

    asyncio.run(scenario())


# ---- cuándo se dispara (BRIEFING §2) ----------------------------------------------------------------------------------------
def test_a_discarded_document_never_generates_a_notification(sse):
    async def scenario():
        async with AsgiStream(sse.app) as stream:
            await stream.frame()  # retry
            discarded = await asyncio.to_thread(upload_pdf, sse.client, PDF_INVALID)
            assert sse.client.get(f"/rfp/tickets/{discarded}").json()["status"] == "descartado"
            with pytest.raises(TimeoutError):
                await stream.frame(timeout=0.3)  # no era una RFP válida: nadie se entera
            valid = await register_rfp_async(sse.client)
            assert json.loads(parse_frame(await stream.frame())["data"])["ticket_id"] == valid  # y la siguiente RFP sí

    asyncio.run(scenario())


def test_a_ticket_is_announced_only_once(sse):
    with Session(sse.engine) as session:
        ticket = repository.create_ticket(session, raw_pdf_path="x.pdf", original_filename="x.pdf", uploaded_by=None)
    store = SqlRfpStore(lambda: Session(sse.engine))
    assert store.announce_ticket(ticket.ticket_id)["ticket_id"] == ticket.ticket_id
    assert store.announce_ticket(ticket.ticket_id) is None  # un reproceso no vuelve a avisar


def test_replay_follows_announcement_order_not_ticket_id_order(sse):
    """El ticket 1 se sube antes pero se clasifica después que el 2: el cliente que ya vio el aviso del 2 NO debe perder el del 1."""
    with Session(sse.engine) as session:
        first = repository.create_ticket(session, raw_pdf_path="a.pdf", original_filename="a.pdf", uploaded_by=None).ticket_id
        second = repository.create_ticket(session, raw_pdf_path="b.pdf", original_filename="b.pdf", uploaded_by=None).ticket_id
    store = SqlRfpStore(lambda: Session(sse.engine))
    store.announce_ticket(second)
    seen_by_client = event_for(sse, second).id
    store.announce_ticket(first)

    async def scenario():
        async with AsgiStream(sse.app, headers={"Last-Event-ID": str(seen_by_client)}) as stream:
            await stream.frame()
            assert json.loads(parse_frame(await stream.frame())["data"])["ticket_id"] == first

    asyncio.run(scenario())


# ---- JWT ---------------------------------------------------------------------------------------------------------------
def test_stream_requires_the_same_jwt_as_the_backoffice_api(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    app = FastAPI()  # SIN override de autenticación
    app.include_router(create_router(store_factory=lambda: SqlRfpStore(lambda: Session(engine)), llm=ScriptedRfpModel()))
    client = TestClient(app)
    assert client.get("/rfp/events").status_code == 401  # sin token
    assert client.get("/rfp/events", headers={"Authorization": "Bearer no-es-un-jwt"}).status_code == 401
    assert client.get("/rfp/events", headers={"Authorization": "Basic abc"}).status_code == 401


def test_stream_accepts_a_valid_login_jwt_on_the_real_app(auth_headers):
    headers = auth_headers()

    async def scenario():
        async with AsgiStream(main_module.app, headers=headers) as stream:
            assert stream.status == 200 and stream.headers["content-type"] == "text/event-stream"
            assert (await stream.frame()) == "retry: 3000"

    asyncio.run(scenario())


# ---- keep-alive ------------------------------------------------------------------------------------------------------------
def test_keep_alive_comment_frames_are_sent_when_there_is_no_traffic(sse, monkeypatch):
    monkeypatch.setenv("RFP_SSE_KEEPALIVE_SECONDS", "0.05")

    async def scenario():
        async with AsgiStream(sse.app) as stream:
            assert (await stream.frame()) == "retry: 3000"
            assert (await stream.frame()) == ": keep-alive"  # comentario SSE: el cliente lo ignora, los proxies no cierran
            assert (await stream.frame()) == ": keep-alive"

    asyncio.run(scenario())


# ---- recuperación (Last-Event-ID) y duplicados -------------------------------------------------------------------------------
def test_last_event_id_replays_only_missed_tickets_in_order_and_then_continues_live(sse):
    for _ in range(3):
        register_rfp(sse.client)  # 1, 2 y 3 se registraron mientras no había nadie conectado

    async def scenario():
        async with AsgiStream(sse.app, headers={"Last-Event-ID": str(event_for(sse, 1).id)}) as stream:
            assert (await stream.frame()) == "retry: 3000"
            replayed = [parse_frame(await stream.frame()) for _ in range(2)]
            assert [f["id"] for f in replayed] == [str(event_for(sse, 2).id), str(event_for(sse, 3).id)]  # el 1 ya lo tenía
            assert {f["event"] for f in replayed} == {"rfp_ticket_created"}
            assert json.loads(replayed[0]["data"])["ticket_id"] == 2
            await register_rfp_async(sse.client)  # y sigue en vivo después de recuperar
            assert parse_frame(await stream.frame())["id"] == str(event_for(sse, 4).id)
            with pytest.raises(TimeoutError):
                await stream.frame(timeout=0.2)  # nada más: ni repetidos ni huecos

    asyncio.run(scenario())


def test_without_last_event_id_there_is_no_replay(sse):
    register_rfp(sse.client)

    async def scenario():
        async with AsgiStream(sse.app) as stream:
            assert (await stream.frame()) == "retry: 3000"
            with pytest.raises(TimeoutError):
                await stream.frame(timeout=0.2)  # el cliente carga la lista por su cuenta; el stream solo trae lo nuevo

    asyncio.run(scenario())


def test_an_event_published_while_replaying_is_not_delivered_twice(sse):
    register_rfp(sse.client)  # ticket 1 ya en base de datos

    async def scenario():
        async with AsgiStream(sse.app, headers={"Last-Event-ID": "0"}) as stream:
            await stream.frame()  # retry
            assert parse_frame(await stream.frame())["id"] == str(event_for(sse, 1).id)  # recuperado de la base de datos
            # El mismo ticket llega también por el broker (carrera entre recuperación y vivo): no debe repetirse.
            sse.broker.publish(event_for(sse, 1))
            with pytest.raises(TimeoutError):
                await stream.frame(timeout=0.2)

    asyncio.run(scenario())


def test_invalid_last_event_id_is_ignored_instead_of_failing(sse):
    register_rfp(sse.client)

    async def scenario():
        async with AsgiStream(sse.app, headers={"Last-Event-ID": "no-es-un-numero"}) as stream:
            assert stream.status == 200
            assert (await stream.frame()) == "retry: 3000"
            with pytest.raises(TimeoutError):
                await stream.frame(timeout=0.2)

    asyncio.run(scenario())


# ---- conexiones independientes y limpieza ---------------------------------------------------------------------------------------
def test_each_connection_gets_every_event_independently_and_is_released_on_disconnect(sse):
    async def scenario():
        async with AsgiStream(sse.app) as a, AsgiStream(sse.app) as b:
            await a.frame(), await b.frame()
            assert sse.broker.connections == 2
            await register_rfp_async(sse.client)
            assert parse_frame(await a.frame())["id"] == parse_frame(await b.frame())["id"] == str(event_for(sse, 1).id)
        await asyncio.sleep(0.05)
        assert sse.broker.connections == 0  # cerrar la pestaña libera la cola

    asyncio.run(scenario())


def test_a_slow_connection_is_closed_so_it_can_recover_instead_of_losing_events_silently(tmp_path):
    broker = RfpEventBroker(queue_size=2)
    engine = create_engine(f"sqlite:///{tmp_path / 'slow.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(create_router(store_factory=lambda: SqlRfpStore(lambda: Session(engine)), llm=ScriptedRfpModel(), broker=broker))
    app.dependency_overrides[get_current_user] = lambda: {"email": "x@brasaland.test"}

    async def scenario():
        async with AsgiStream(app) as stream:
            await stream.frame()
            for n in range(1, 6):  # ráfaga: la cola (2) se desborda antes de que la conexión consuma
                broker.publish(make_event(n))
            with pytest.raises(EOFError):
                for _ in range(10):
                    await stream.frame()

    asyncio.run(scenario())


# ---- piezas puras ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [(None, None), ("", None), ("7", 7), (" 12 ", 12), ("0", 0), ("-1", None), ("abc", None), ("1.5", None)])
def test_parse_last_event_id_only_accepts_non_negative_integers(raw, expected):
    assert parse_last_event_id(raw) == expected


def make_event(ticket_id: int, client_name: str | None = "Andes Tech"):
    return ticket_created_event(ticket_id=ticket_id, rfp_id=f"RFP-{ticket_id}", client_name=client_name, location="Medellín",
                                service_type="recurring_catering", status="analizando", created_at="2026-01-01T00:00:00",
                                announced_at=datetime(2026, 1, 1) + timedelta(seconds=ticket_id))


def test_event_id_is_a_microsecond_timestamp_that_round_trips():
    from app.rfp.events import announced_after
    moment = datetime(2026, 7, 24, 14, 32, 0, 123456)
    assert announced_after(event_id_of(moment)) == moment
    assert event_id_of(moment) < event_id_of(moment + timedelta(microseconds=1))


def test_format_event_keeps_data_on_one_line_and_ends_with_a_blank_line():
    text = format_event(make_event(9, client_name="Cliente\ncon salto"))
    assert text.endswith("\n\n") and text.count("\n") == 4  # id, event, data + línea en blanco
    assert json.loads(text.splitlines()[2].removeprefix("data: "))["client_name"] == "Cliente\ncon salto"
