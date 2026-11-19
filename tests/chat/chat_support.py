"""Dobles para las pruebas del chat en vivo: un proveedor de LLM falso que hace streaming controlable (sin red ni claves)."""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

from langgraph.checkpoint.memory import InMemorySaver

from data.pipelines import rag
from services.agent.chat.broker import ChatBroker
from services.agent.chat.manager import ChatSessionManager
from services.agent.chat.store import ChatStore
from services.agent.nodes import AgentDependencies
from services.agent.service import AgentService
from services.agent.tracing import TraceStore

CONTEXT = [{"company": "brasaland", "source_document": "faq", "section": "Horarios", "language": "es", "chunk_index": 0,
            "text": "El proveedor de Miami entrega los martes."}]


class FakeStream:
    """Stream del proveedor: entrega `tokens` uno a uno; si `gate_after` está definido se detiene tras esos tokens hasta que el
    test abra `gate` (así el test controla el instante en que llega la interrupción). `close()` queda registrado."""

    def __init__(self, tokens: list[str], gate_after: int | None = None):
        self.tokens, self.gate_after = tokens, gate_after
        self.gate = threading.Event()
        self.reached_gate = threading.Event()
        self.closed = False
        self.produced = 0

    def __iter__(self):
        for index, token in enumerate(self.tokens):
            if self.gate_after is not None and index == self.gate_after:
                self.reached_gate.set()
                self.gate.wait(timeout=5)
            self.produced += 1
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=token))])

    def close(self) -> None:
        self.closed = True


class FakeProvider:
    """`script(question) -> FakeStream`. Registra las peticiones y las llamadas sin streaming."""

    def __init__(self, script):
        self.script = script
        self.streams: list[FakeStream] = []
        self.questions: list[str] = []
        self.blocking_calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, *, model, messages, temperature, stream=False):
        question = messages[-1]["content"].split("PREGUNTA:\n")[-1]
        self.questions.append(question)
        fake = self.script(question)
        self.streams.append(fake)
        if stream:
            return fake
        self.blocking_calls += 1
        text = "".join(fake.tokens)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def install_provider(monkeypatch, provider: FakeProvider) -> None:
    monkeypatch.setattr(rag, "get_generation_client", lambda: provider)
    monkeypatch.setattr(rag, "load_settings", lambda: SimpleNamespace(generation_model="fake-model"))


def real_agent_service(tmp_path, generate_fn=None) -> AgentService:
    """El AgentService REAL (grafo de LangGraph compilado) con dependencias de prueba; la generación pasa por `rag.complete`."""
    deps = AgentDependencies(
        retrieve_fn=lambda question: list(CONTEXT),
        generate_fn=generate_fn or (lambda question, context: rag.complete(rag.build_messages(question, context))),
    )
    return AgentService(deps, checkpointer=InMemorySaver(), trace_store=TraceStore(tmp_path / "traces"))


def make_manager(service) -> ChatSessionManager:
    return ChatSessionManager(ChatStore(":memory:"), ChatBroker(), lambda: service)


async def collect(subscription, until: str, *, count: int = 1, timeout: float = 5.0) -> list[dict]:
    """Lee eventos de la suscripción hasta ver `count` veces `until` (inclusive)."""
    seen: list[dict] = []
    hits = 0
    async def read():
        nonlocal hits
        while True:
            event = await subscription.queue.get()
            seen.append(event)
            if event["event"] == until:
                hits += 1
                if hits >= count:
                    return
    await asyncio.wait_for(read(), timeout)
    return seen


def names(events: list[dict]) -> list[str]:
    return [event["event"] for event in events]
