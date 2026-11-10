"""Nodos de los guardrails (se añaden al grafo solo si el agente se construye con `AgentDependencies.guardrails`).

    input_guard        decide qué hacer con el mensaje ANTES de consultar nada: seguir, rechazar o responder small talk
    refuse_request     rechazo firme con texto fijo (jailbreak, dato confidencial, tarea personal, crisis); no se hace la tarea
    casual_reply       small talk / trivia: respuesta breve del modelo; la reconducción obligatoria la garantiza output_guard
    isolate_external   sanea los fragmentos del RAG y los resultados de las tools: son DATOS, nunca instrucciones
    output_guard       valida la respuesta del modelo (estructura, fuga del prompt, datos confidenciales, reconducción)

Cada intervención se registra (con su tipo de fallo) en el monitor y se devuelve en `state["guardrails"]`.
"""
from __future__ import annotations

from typing import Callable

from .guardrails import policy
from .guardrails.external import isolate_chunks
from .guardrails.input_guard import ALLOW, BLOCK, CASUAL, CONTENT, SECURITY
from .guardrails.output_guard import check_output
from .guardrails.patterns import JAILBREAK_FAMILIES
from .guardrails.text import excerpt
from .nodes import AgentDependencies, tool_chunks
from .state import STATUS_BLOCKED, STATUS_REDIRECTED, AgentState

NODE_INPUT_GUARD = "input_guard"
NODE_REFUSE = "refuse_request"
NODE_CASUAL = "casual_reply"
NODE_ISOLATE = "isolate_external"
NODE_OUTPUT_GUARD = "output_guard"
GUARD_NODE_NAMES = (NODE_INPUT_GUARD, NODE_REFUSE, NODE_CASUAL, NODE_ISOLATE, NODE_OUTPUT_GUARD)

ROUTE_CONTINUE = "continue"
ROUTE_BLOCK = "block"
ROUTE_CASUAL = "casual"
ROUTE_PROPOSE = "propose"
ROUTE_END = "end"

_OVERRIDE_CODES = {code for code, _ in JAILBREAK_FAMILIES}


def guardrail_for(reason: str) -> str:
    """Nombre del guardrail que corresponde al motivo de un bloqueo de entrada."""
    if reason in _OVERRIDE_CODES:
        return "instruction_override"
    if reason.startswith("recipe_"):
        return "recipe_extraction"
    if reason in ("confidential_commercial", "employee_data", "customer_pii"):
        return "sensitive_request"
    if reason in ("personal_task", "personal_advice"):
        return "personal_use"
    if reason == "personal_crisis":
        return "wellbeing"
    return "casual_redirect"


def _record(deps: AgentDependencies, state: AgentState, events: list[dict]) -> list[dict]:
    """Registra cada evento en el monitor y devuelve el historial acumulado de la corrida para el estado."""
    for event in events:
        deps.guardrails.monitor.record(event, conversation_id=state.get("conversation_id"), run_id=state.get("run_id"),
                                       excerpt=excerpt(state.get("original_question") or state.get("question", "")))
    return [*state.get("guardrails", []), *events]


def make_input_guard_node(deps: AgentDependencies) -> Callable[[AgentState], dict]:
    def input_guard(state: AgentState) -> dict:
        guard = deps.guardrails
        conversation = state.get("conversation_id")
        pending = bool(deps.memory and conversation and deps.memory.has_pending(conversation))
        decision = guard.inspect(state["question"], conversation, pending_proposal=pending)
        update: dict = {"guardrails_enabled": True, "language": decision.language, "scope": decision.scope,
                        "original_question": state["question"]}
        if decision.action == ALLOW:
            return update
        event = {"guardrail": guardrail_for(decision.reason), "kind": decision.kind, "reason": decision.reason,
                 "action": "redirected" if decision.action == CASUAL else "blocked", **decision.detail}
        update["guardrails"] = _record(deps, state, [event])
        update["guard"] = {"action": decision.action, "refusal": decision.refusal}
        if decision.action == CASUAL:
            update["scope"] = "casual"
        return update

    return input_guard


def route_after_input_guard(state: AgentState) -> str:
    action = (state.get("guard") or {}).get("action", ALLOW)
    return {BLOCK: ROUTE_BLOCK, CASUAL: ROUTE_CASUAL}.get(action, ROUTE_CONTINUE)


def refuse_request(state: AgentState) -> dict:
    lang = state.get("language", "es")
    key = (state.get("guard") or {}).get("refusal") or "personal"
    return {"answer": policy.REFUSALS[key][lang], "status": STATUS_BLOCKED}


def make_casual_node(deps: AgentDependencies) -> Callable[[AgentState], dict]:
    def casual_reply(state: AgentState) -> dict:
        lang = state.get("language", "es")
        try:
            answer = deps.guardrails.casual_fn(state["question"])
        except Exception:  # noqa: BLE001 - el small talk nunca debe tumbar la corrida: texto fijo + reconducción
            answer = ""
        return {"answer": answer or policy.CASUAL_FALLBACK[lang], "status": STATUS_REDIRECTED, "scope": "casual",
                "tool_results": [], "context": []}

    return casual_reply


def make_isolate_node(deps: AgentDependencies) -> Callable[[AgentState], dict]:
    def isolate_external(state: AgentState) -> dict:
        raw = [*state.get("context", []), *tool_chunks(state.get("tool_results", []))]
        safe, findings = isolate_chunks(raw)
        events = [{"guardrail": "external_content_isolation", "kind": SECURITY, "reason": f.family, "action": "neutralized",
                   "source": f.source} for f in findings]
        update: dict = {"safe_context": safe}
        if events:
            update["guardrails"] = _record(deps, state, events)
        return update

    return isolate_external


def make_output_guard_node(deps: AgentDependencies) -> Callable[[AgentState], dict]:
    def output_guard(state: AgentState) -> dict:
        verdict = check_output(state.get("answer"), question=state.get("original_question") or state.get("question", ""),
                               language=state.get("language", "es"), casual=state.get("scope") == "casual")
        update: dict = {"answer": verdict.answer}
        if verdict.replaced:
            update["proposal_raw"] = None  # lo que el modelo propuso recordar salió de una respuesta descartada
        if verdict.events:
            update["guardrails"] = _record(deps, state, verdict.events)
        return update

    return output_guard


def make_route_after_output(deps: AgentDependencies) -> Callable[[AgentState], str]:
    def route_after_output(state: AgentState) -> str:
        return ROUTE_PROPOSE if deps.memory is not None else ROUTE_END

    return route_after_output
