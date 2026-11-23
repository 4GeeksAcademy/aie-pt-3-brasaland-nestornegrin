"""Nodos del grafo y funciones de enrutamiento (aristas condicionales).

Cada nodo hace UNA cosa y devuelve solo las claves del estado que cambia:

    receive_question   valida y normaliza la pregunta
    retrieve_context   llama a `retrieve()` (data/pipelines/rag.py)
    generate_answer    llama a `generate_answer(question, context)` con el contexto que YA produjo el nodo anterior
    no_information     responde con honestidad cuando no se recuperó nada (sin llamar al modelo)
    reject_question    devuelve un mensaje claro cuando la pregunta no es válida

Ningún nodo llama a `query()`: eso volvería a ejecutar la recuperación dentro de la generación y taparía justo el
flujo que este grafo hace visible. Las dependencias entran por `AgentDependencies` para poder probar el grafo sin
Qdrant ni modelos reales.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .state import (
    STATUS_ANSWERED,
    STATUS_INVALID_QUESTION,
    STATUS_NO_INFORMATION,
    STATUS_RECEIVED,
    AgentState,
)

# Nombres de nodos (no pueden coincidir con claves del estado: LangGraph lo rechaza).
NODE_RECEIVE = "receive_question"
NODE_RETRIEVE = "retrieve_context"
NODE_GENERATE = "generate_answer"
NODE_NO_INFORMATION = "no_information"
NODE_REJECT = "reject_question"
NODE_NAMES = (NODE_RECEIVE, NODE_RETRIEVE, NODE_GENERATE, NODE_NO_INFORMATION, NODE_REJECT)

# Nombres de las salidas de las aristas condicionales.
ROUTE_RETRIEVE = "retrieve"
ROUTE_REJECT = "reject"
ROUTE_GENERATE = "generate"
ROUTE_NO_INFORMATION = "no_information"

MAX_QUESTION_LENGTH = 1000
NO_INFORMATION_ANSWER = "No tengo información suficiente en la base de conocimiento de Brasaland para responder eso."
EMPTY_QUESTION_ANSWER = "La pregunta no puede estar vacía."
TOO_LONG_QUESTION_ANSWER = f"La pregunta no puede superar los {MAX_QUESTION_LENGTH} caracteres."


@dataclass(frozen=True)
class AgentDependencies:
    """Funciones que usan los nodos de recuperación y generación."""

    retrieve_fn: Callable[[str], list[dict]]
    generate_fn: Callable[[str, list[dict]], str]


def default_dependencies() -> AgentDependencies:
    """Las funciones reales del RAG, reutilizadas desde `data/pipelines/rag.py` (sin copiarlas)."""
    from data.pipelines.rag import generate_answer, retrieve

    return AgentDependencies(retrieve_fn=lambda question: retrieve(question), generate_fn=generate_answer)


# --------------------------------------------------------------------------------------------------------------
# Nodos
# --------------------------------------------------------------------------------------------------------------
def receive_question(state: AgentState) -> dict:
    raw = state.get("question")
    question = raw.strip() if isinstance(raw, str) else ""
    if not question or len(question) > MAX_QUESTION_LENGTH:
        return {"question": question, "status": STATUS_INVALID_QUESTION}
    return {"question": question, "status": STATUS_RECEIVED}


def reject_question(state: AgentState) -> dict:
    question = state.get("question") or ""
    answer = TOO_LONG_QUESTION_ANSWER if len(question) > MAX_QUESTION_LENGTH else EMPTY_QUESTION_ANSWER
    return {"answer": answer, "status": STATUS_INVALID_QUESTION}


def make_retrieve_node(deps: AgentDependencies) -> Callable[[AgentState], dict]:
    def retrieve_context(state: AgentState) -> dict:
        return {"context": deps.retrieve_fn(state["question"])}

    return retrieve_context


def make_generate_node(deps: AgentDependencies) -> Callable[[AgentState], dict]:
    def generate_answer(state: AgentState) -> dict:
        return {"answer": deps.generate_fn(state["question"], state.get("context", [])), "status": STATUS_ANSWERED}

    return generate_answer


def no_information(state: AgentState) -> dict:
    return {"answer": NO_INFORMATION_ANSWER, "status": STATUS_NO_INFORMATION}


# --------------------------------------------------------------------------------------------------------------
# Aristas condicionales
# --------------------------------------------------------------------------------------------------------------
def route_after_receive(state: AgentState) -> str:
    """Pregunta vacía o demasiado larga -> error claro (sin recuperar); si no, a recuperar."""
    return ROUTE_REJECT if state.get("status") == STATUS_INVALID_QUESTION else ROUTE_RETRIEVE


def route_after_retrieve(state: AgentState) -> str:
    """Nada superó el umbral -> respuesta honesta (sin forzar la generación sobre un contexto vacío)."""
    return ROUTE_GENERATE if state.get("context") else ROUTE_NO_INFORMATION
