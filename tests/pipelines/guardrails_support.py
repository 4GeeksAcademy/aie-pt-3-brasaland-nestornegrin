"""Dobles de prueba de los guardrails: un agente completo (grafo real) con un «modelo» que registra todo lo que recibe.

El modelo falso es adrede el PEOR caso: no se defiende solo (devuelve lo que el test le diga, o incluso lo que una
inyección le pide). Así cada prueba comprueba que la defensa está en el código que rodea al modelo, no en que el modelo
«se porte bien».
"""
from __future__ import annotations

from typing import Callable

from agent_support import FakeBackend, chunk
from langgraph.checkpoint.memory import InMemorySaver

from services.agent.guardrails import Guardrails, GuardrailMonitor, casual_answer, secure_generate_answer
from services.agent.mcp_tools import McpInventoryTool, McpTicketTool
from services.agent.nodes import AgentDependencies
from services.agent.service import AgentService
from services.agent.tracing import TraceStore

ANSWER = "Revisa el playbook de cierre y confirma el stock de carbón antes del turno.\n\nFuente: playbook — Cierre"


class GuardedAgent:
    def __init__(self, tmp_path, *, context: list[dict] | None = None, reply: str | Callable[[list[dict]], str] = ANSWER,
                 casual_reply: str = "Tokio va unas 14 horas por delante de Bogotá.", tickets=None, memory=None,
                 structured_fn=None, log_file: bool = False):
        self.context = context if context is not None else [chunk("playbook", "Cierre", "El cierre se hace a las 10pm.")]
        self.reply, self.casual_reply = reply, casual_reply
        self.model_calls: list[list[dict]] = []  # mensajes que recibió el modelo de respuesta
        self.casual_calls: list[list[dict]] = []
        self.retrieve_calls: list[str] = []
        self.monitor = GuardrailMonitor(tmp_path / "guardrails.jsonl", write_file=log_file)
        backend = FakeBackend(tickets=tickets)
        gateway = backend.client()
        self.guardrails = Guardrails(monitor=self.monitor, casual_fn=lambda m: casual_answer(m, complete_fn=self._casual))
        deps = AgentDependencies(
            retrieve_fn=self._retrieve, generate_fn=lambda q, c: secure_generate_answer(q, c, complete_fn=self._complete),
            ticket_fn=McpTicketTool(gateway), inventory_fn=McpInventoryTool(gateway), guardrails=self.guardrails,
            memory=memory, structured_fn=structured_fn)
        self.service = AgentService(deps, checkpointer=InMemorySaver(), trace_store=TraceStore(tmp_path / "traces"))

    def _retrieve(self, question: str) -> list[dict]:
        self.retrieve_calls.append(question)
        return list(self.context)

    def _complete(self, messages: list[dict]) -> str:
        self.model_calls.append(messages)
        return self.reply(messages) if callable(self.reply) else self.reply

    def _casual(self, messages: list[dict]) -> str:
        self.casual_calls.append(messages)
        return self.casual_reply

    def say(self, message: str, conversation: str = "conv-guard-0001", user: str = "carlos.jimenez"):
        return self.service.run(message, conversation_id=conversation, actor=user)

    @property
    def model_was_called(self) -> bool:
        return bool(self.model_calls or self.casual_calls)

    def kinds(self) -> list[str]:
        return [event["kind"] for event in self.monitor.events()]
