"""Estado del grafo del agente.

Es la información MÍNIMA que necesita un nodo para decidir el siguiente paso: la pregunta, el contexto que devolvió
`retrieve()`, la respuesta y un estado de la corrida que usan las aristas condicionales. No se guarda el historial de
conversación: este agente responde preguntas aisladas y arrastrar mensajes anteriores solo engordaría cada checkpoint
sin que ningún nodo los leyera. Si la Parte 2 añade conversación, se añade entonces un campo con su justificación.
"""
from __future__ import annotations

from typing import TypedDict

# Valores de `AgentState["status"]`.
STATUS_RECEIVED = "received"  # la pregunta es válida y sigue hacia la recuperación
STATUS_ANSWERED = "answered"  # respuesta generada a partir de contexto recuperado
STATUS_NO_INFORMATION = "no_information"  # ningún fragmento superó el umbral: se responde con honestidad
STATUS_INVALID_QUESTION = "invalid_question"  # pregunta vacía o demasiado larga: no se recupera nada

FINAL_STATUSES = (STATUS_ANSWERED, STATUS_NO_INFORMATION, STATUS_INVALID_QUESTION)


class AgentState(TypedDict, total=False):
    question: str  # pregunta del usuario, ya recortada
    context: list[dict]  # payloads que devolvió `retrieve()` (solo los que superan el umbral)
    answer: str  # respuesta final, o el mensaje claro cuando no hay respuesta
    status: str  # uno de los STATUS_* de arriba
