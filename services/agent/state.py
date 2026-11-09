"""Estado del grafo del agente.

Es la información MÍNIMA que necesita un nodo para decidir el siguiente paso: la pregunta, el contexto que devolvió
`retrieve()`, la respuesta y un estado de la corrida que usan las aristas condicionales. No se guarda el historial de
conversación: este agente responde preguntas aisladas y arrastrar mensajes anteriores solo engordaría cada checkpoint
sin que ningún nodo los leyera.

La Parte 2 (tools) añade solo dos campos, ambos los lee algún nodo: `route` (qué fuentes decidió usar el enrutador y por
qué; lo leen las aristas) y `tool_results` (lo que devolvieron las tools; lo leen la generación y el fallback).
Sigue sin haber historial de conversación.
"""
from __future__ import annotations

from typing import TypedDict

# Valores de `AgentState["status"]`.
STATUS_RECEIVED = "received"  # la pregunta es válida y sigue hacia la recuperación
STATUS_ANSWERED = "answered"  # respuesta generada a partir de contexto recuperado
STATUS_NO_INFORMATION = "no_information"  # ningún fragmento superó el umbral: se responde con honestidad
STATUS_INVALID_QUESTION = "invalid_question"  # pregunta vacía o demasiado larga: no se recupera nada
STATUS_TOOL_FALLBACK = "tool_fallback"  # la tool falló o el recurso no existe: respuesta honesta, sin inventar

FINAL_STATUSES = (STATUS_ANSWERED, STATUS_NO_INFORMATION, STATUS_INVALID_QUESTION, STATUS_TOOL_FALLBACK)


class AgentState(TypedDict, total=False):
    question: str  # pregunta del usuario, ya recortada
    context: list[dict]  # payloads que devolvió `retrieve()` (solo los que superan el umbral)
    answer: str  # respuesta final, o el mensaje claro cuando no hay respuesta
    status: str  # uno de los STATUS_* de arriba
    route: dict  # plan del enrutador: fuentes (tickets / inventory / rag), consultas y motivo
    tool_results: list[dict]  # una entrada por tool ejecutada: {"tool", "outcome", "result"}
