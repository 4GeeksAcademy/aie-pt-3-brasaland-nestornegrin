"""Guardrails del Manager support agent (Hito 8 · Parte 2). Ver `docs/agent/guardrails.md`.

Capas, de fuera hacia dentro:  input_guard → (external → prompts) → modelo → output_guard, todo observado por `monitor`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from .external import isolate_chunks, sanitize_text
from .input_guard import (CONTENT, SECURITY, STRUCTURAL, ConversationGuardState, GuardStateStore, InputDecision,
                          has_domain_anchor, inspect)
from .input_guard import inspect as _inspect
from .monitor import GuardrailMonitor, summarize
from .output_guard import OutputVerdict, check_output
from .prompts import CANARY, SYSTEM_PROMPT, build_messages, casual_answer, secure_generate_answer


@dataclass
class Guardrails:
    """Todo lo que los nodos necesitan, en un solo objeto inyectable (en las pruebas: estado y monitor propios, modelo falso)."""

    states: GuardStateStore = field(default_factory=GuardStateStore)
    monitor: GuardrailMonitor = field(default_factory=GuardrailMonitor)
    casual_fn: Callable[[str], str] = casual_answer  # (mensaje) -> respuesta breve; falla → texto fijo + reconducción

    def inspect(self, text: str, conversation_id: str | None, *, pending_proposal: bool = False) -> InputDecision:
        return _inspect(text, self.states.get(conversation_id), pending_proposal=pending_proposal)


def guardrails_enabled() -> bool:
    return os.environ.get("AGENT_GUARDRAILS_ENABLED", "1") != "0"  # interruptor para volver al agente sin guardrails


__all__ = ["CANARY", "CONTENT", "SECURITY", "STRUCTURAL", "SYSTEM_PROMPT", "ConversationGuardState", "GuardStateStore",
           "Guardrails", "GuardrailMonitor", "InputDecision", "OutputVerdict", "build_messages", "casual_answer",
           "check_output", "guardrails_enabled", "has_domain_anchor", "inspect", "isolate_chunks", "sanitize_text",
           "secure_generate_answer", "summarize"]
