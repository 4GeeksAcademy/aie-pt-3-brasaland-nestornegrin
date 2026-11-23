"""Nodos del flujo de memoria (se añaden al grafo solo si el agente se construye con `AgentDependencies.memory`).

    resolve_pending      ¿había una propuesta pendiente? Clasifica este mensaje contra ella (sí / no / edición /
                         ambigua), la resuelve y devuelve el resto del mensaje como pregunta normal
    acknowledge_memory   el mensaje solo respondía a la propuesta: confirma lo que pasó, sin consultar nada más
    recall_memory        trae los recuerdos relevantes (máx. 5) para la pregunta
    generate_answer      (versión con memoria) UNA llamada: respuesta + `propuesta_memoria`
    propose_memory       cierra TODA respuesta con contenido: antepone lo que pasó con la propuesta anterior y valida
                         la propuesta nueva con la política; si procede, la deja PENDIENTE y se la plantea al usuario
                         al final de la misma respuesta. Nunca escribe memoria.
"""
from __future__ import annotations

from typing import Callable

from .memory.models import StructuredAnswer
from .nodes import (
    MAX_QUESTION_LENGTH,
    NO_INFORMATION_ANSWER,
    TOO_LONG_QUESTION_ANSWER,
    AgentDependencies,
    failed_tools,
    failure_message,
    tool_chunks,
)
from .state import (
    STATUS_ANSWERED,
    STATUS_INVALID_QUESTION,
    STATUS_MEMORY_DECISION,
    STATUS_NO_INFORMATION,
    AgentState,
)

NODE_RESOLVE = "resolve_pending"
NODE_MEMORY_ACK = "acknowledge_memory"
NODE_RECALL = "recall_memory"
NODE_PROPOSE = "propose_memory"
MEMORY_NODE_NAMES = (NODE_RESOLVE, NODE_MEMORY_ACK, NODE_RECALL, NODE_PROPOSE)

ROUTE_ACK = "acknowledge"


def _actor(state: AgentState) -> str:
    return state.get("actor") or "anonymous"


def make_resolve_node(deps: AgentDependencies) -> Callable[[AgentState], dict]:
    def resolve_pending(state: AgentState) -> dict:
        resolution = deps.memory.resolve_pending(
            conversation_id=state["conversation_id"], message=state["question"], actor=_actor(state),
            run_id=state.get("run_id"))
        update: dict = {"memory_enabled": True}
        if resolution is None:
            return update
        update["memory_resolution"] = {**resolution.to_dict(), "notice": resolution.notice}
        remainder = resolution.remainder.strip()
        if not remainder:  # solo era la respuesta a la propuesta
            update.update(answer=resolution.notice, status=STATUS_MEMORY_DECISION)
            return update
        if len(remainder) > MAX_QUESTION_LENGTH:
            update.update(answer=f"{resolution.notice}\n\n{TOO_LONG_QUESTION_ANSWER}", status=STATUS_MEMORY_DECISION)
            return update
        update["question"] = remainder  # el usuario respondió Y siguió con otra pregunta: se atiende esa pregunta
        return update

    return resolve_pending


def route_after_resolve(state: AgentState) -> str:
    return ROUTE_ACK if state.get("status") in (STATUS_MEMORY_DECISION, STATUS_INVALID_QUESTION) else "route"


def acknowledge_memory(state: AgentState) -> dict:
    return {"answer": state["answer"], "status": STATUS_MEMORY_DECISION}


def make_recall_node(deps: AgentDependencies) -> Callable[[AgentState], dict]:
    def recall_memory(state: AgentState) -> dict:
        return {"memories": deps.memory.recall(state["question"])}

    return recall_memory


def make_memory_generate_node(deps: AgentDependencies) -> Callable[[AgentState], dict]:
    def generate_answer(state: AgentState) -> dict:
        context = [*state.get("context", []), *tool_chunks(state.get("tool_results", []))]
        memories = state.get("memories", [])
        result: StructuredAnswer = deps.structured_fn(state["question"], context, memories)
        if not context and not memories and not result.proposal:
            # Sin evidencia y sin nada que recordar: respuesta honesta y fija, igual que sin memoria.
            return {"answer": NO_INFORMATION_ANSWER, "status": STATUS_NO_INFORMATION}
        answer = result.answer
        notices = [failure_message(entry) for entry in failed_tools(state)]
        if notices:
            answer = "\n\n".join([answer, *notices])
        update: dict = {"answer": answer, "status": STATUS_ANSWERED}
        if result.proposal:
            update["proposal_raw"] = result.proposal
        return update

    return generate_answer


def make_propose_node(deps: AgentDependencies) -> Callable[[AgentState], dict]:
    def propose_memory(state: AgentState) -> dict:
        outcome = deps.memory.propose(
            state.get("proposal_raw"), conversation_id=state["conversation_id"], message=state["question"],
            actor=_actor(state), run_id=state.get("run_id"))
        resolution = state.get("memory_resolution")
        prefix = f"{resolution['notice']}\n\n" if resolution else ""  # qué pasó con la propuesta anterior
        if outcome is None:
            return {"answer": f"{prefix}{state['answer']}"} if prefix else {}
        return {"answer": f"{prefix}{state['answer']}\n\n{outcome.question}", "memory_proposal": outcome.to_dict()}

    return propose_memory
