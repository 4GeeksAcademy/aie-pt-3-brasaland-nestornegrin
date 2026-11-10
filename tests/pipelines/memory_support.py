"""Dobles de prueba de la memoria (sin red ni claves): un «modelo» guionizado y un clasificador determinista.

El modelo guionizado devuelve, para cada mensaje, la respuesta y la `propuesta_memoria` que DEBERÍA producir un buen
modelo según el BRIEFING; así se prueba todo lo que rodea al modelo (política, confirmación, auditoría, consolidación)
sin depender de él. La calidad del modelo real se comprueba aparte, con las corridas reales (docs/agent/memory.md).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from services.agent.memory import AgentMemory, Decision, Intent, SqliteMemoryStore, StructuredAnswer
from services.agent.nodes import AgentDependencies
from services.agent.service import AgentService
from services.agent.tracing import TraceStore
from langgraph.checkpoint.memory import InMemorySaver

from agent_support import chunk

START = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


class Clock:
    """Reloj controlable para probar caducidades sin esperar."""

    def __init__(self, start: datetime = START):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta) -> None:
        self.now += timedelta(**delta)


def proposal(location: str, category: str, topic: str, fact: str, *, language: str = "es", repeatable: bool = True) -> dict:
    return {"aplica": True, "ubicacion": location, "categoria": category, "tema": topic, "hecho": fact,
            "motivo": "corrección operativa repetible", "repetible": repeatable, "idioma": language}


class ScriptedModel:
    """`structured_fn` del agente: respuesta y propuesta guionizadas por mensaje (por defecto, nada que recordar)."""

    def __init__(self, script: dict[str, tuple[str, dict | None]] | None = None):
        self.script = script or {}
        self.calls: list[tuple[str, list[dict], list[dict]]] = []

    def __call__(self, question: str, context: list[dict], memories: list[dict]) -> StructuredAnswer:
        self.calls.append((question, context, memories))
        if memories and question in self.script and self.script[question][0] == "{memoria}":
            return StructuredAnswer("Según lo que me corrigieron: " + " | ".join(m["fact"] for m in memories))
        answer, raw = self.script.get(question, ("Respuesta de prueba.", None))
        return StructuredAnswer(answer, raw)


def scripted_classifier(pending: dict, message: str) -> Decision:
    """Clasificador de prueba con las mismas SALIDAS que el real (intención + confianza + edición + resto).

    Reglas deliberadamente estrictas, para probar el contrato (no es el clasificador de producción, que es un LLM):
    solo acepta una aprobación/rechazo explícito al inicio del mensaje; lo demás es ambiguo."""
    text = message.strip()
    lowered = text.lower()
    rest = re.split(r"[.;]\s+", text, maxsplit=1)
    remainder = rest[1].strip() if len(rest) == 2 else ""
    if re.match(r"^(sí|si|yes|guárdalo|save it)\b", lowered):
        return Decision(Intent.APPROVE, 0.97, remainder=remainder)
    if re.match(r"^(no|nope|no lo guardes|don't save)\b", lowered):
        return Decision(Intent.REJECT, 0.97, remainder=remainder)
    if lowered.startswith("mejor:") or lowered.startswith("better:"):
        return Decision(Intent.EDIT, 0.95, edited_fact=text.split(":", 1)[1].strip().split(". ")[0])
    return Decision(Intent.AMBIGUOUS, 0.3)


class MemoryAgent:
    """Agente completo (grafo real + almacén SQLite en memoria) con el modelo y el clasificador guionizados."""

    def __init__(self, tmp_path, script: dict | None = None, classify_fn=scripted_classifier, context: list[dict] | None = None):
        self.clock = Clock()
        self.store = SqliteMemoryStore(":memory:", now_fn=self.clock)
        self.memory = AgentMemory(self.store, classify_fn=classify_fn)
        self.model = ScriptedModel(script)
        self.retrieve_calls: list[str] = []
        self._context = context if context is not None else []

        def retrieve(question: str) -> list[dict]:
            self.retrieve_calls.append(question)
            return list(self._context)

        deps = AgentDependencies(retrieve_fn=retrieve, generate_fn=lambda q, c: "no se usa con memoria",
                                 memory=self.memory, structured_fn=self.model)
        self.service = AgentService(deps, checkpointer=InMemorySaver(), trace_store=TraceStore(tmp_path / "traces"))

    def say(self, message: str, conversation: str = "conv-demo-0001", user: str = "carlos.jimenez"):
        return self.service.run(message, conversation_id=conversation, actor=user)

    def active_facts(self) -> list[str]:
        return [memory["fact"] for memory in self.store.active_memories()]


SUPPLIER_FIX = "En realidad el proveedor de vegetales de Medellín entrega los miércoles, no los martes como dijiste antes."
SUPPLIER_FACT = "El proveedor de vegetales de Medellín entrega los miércoles, no los martes."
MIAMI_FIX = "La location de Miami Beach ahora cierra a las 11pm los fines de semana, cambió el mes pasado."
MIAMI_FACT = "Miami Beach ahora cierra a las 11pm los fines de semana."
BLACKOUT_FIX = ("Esa alerta de ventas en cero en la location 7 fue porque hubo un apagón, no fue un error del POS — "
                "ya pasó dos veces este mes.")
BLACKOUT_FACT = "La alerta de ventas en cero en la location 7 fue un apagón, no un error del POS; ya pasó dos veces."

SCRIPT = {
    SUPPLIER_FIX: ("Gracias por la corrección, tomo nota de que entregan los miércoles.",
                   proposal("Medellín", "proveedores", "proveedor_vegetales", SUPPLIER_FACT)),
    MIAMI_FIX: ("Entendido, el cierre de fin de semana es a las 11pm.",
                proposal("Miami Beach", "horarios", "cierre_fin_de_semana", MIAMI_FACT)),
    BLACKOUT_FIX: ("Entendido, fue un apagón y no un fallo del POS.",
                   proposal("Location 7", "incidentes_conocidos", "ventas_en_cero_apagon", BLACKOUT_FACT)),
    "¿Qué día entrega el proveedor de vegetales de Medellín?": ("{memoria}", None),
}
