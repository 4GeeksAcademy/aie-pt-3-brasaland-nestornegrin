"""Endpoint del agente: `POST /agent/query`.

Recibe `{"question": "...", "conversation_id"?, "user"?}` y responde `{"answer", "status", "run_id", "sources", "conversation_id", "memory"}`. Este router NO contiene lógica de negocio:
valida la forma de la petición, invoca el grafo a través de `AgentService` y traduce los fallos a mensajes claros.
`run_id` identifica el trace de la corrida (lo guarda el servidor, no se devuelve por HTTP).

Los errores nunca exponen detalles internos: el detalle va al log del servidor y el cliente recibe un mensaje
genérico (con la referencia `run_id`, para poder encontrar el trace).

Igual que `POST /knowledge/query`, el endpoint es público (el ticket no define autenticación); si se expone fuera
de la red interna conviene protegerlo con `get_current_user`.
"""
from __future__ import annotations

import logging
from typing import Annotated, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StringConstraints

from data.process.rag_config import RagConfigError

from .nodes import MAX_QUESTION_LENGTH
from .service import AgentExecutionError, AgentService, get_agent_service
from .state import STATUS_INVALID_QUESTION

logger = logging.getLogger(__name__)

Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_LENGTH)]


ConversationId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{8,64}$")]
Actor = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class AgentQuery(BaseModel):
    question: Question
    # Memoria: reenvía el `conversation_id` de la respuesta anterior para contestar a una propuesta de memoria.
    conversation_id: ConversationId | None = None
    user: Actor | None = None  # quién escribe (lo declara el cliente; el endpoint es público): va al registro de auditoría


class AgentAnswer(BaseModel):
    answer: str
    status: str
    run_id: str
    sources: list[str] = []  # fuentes consultadas, en orden: "rag", "tool:tickets", "tool:inventory"
    conversation_id: str | None = None
    memory: dict | None = None  # {"resolution": {...}, "proposal": {...}}: qué pasó con la propuesta y si hay una nueva


def create_router(
    service_factory: Callable[[], AgentService] = get_agent_service,
    prefix: str = "/agent",
) -> APIRouter:
    # El grafo se compila aquí, al montar el router (arranque de la API), no en la primera petición.
    service = service_factory()
    router = APIRouter(prefix=prefix, tags=["agent"])

    # Función síncrona a propósito: FastAPI la ejecuta en un hilo mientras se espera a Qdrant y al modelo.
    @router.post("/query", response_model=AgentAnswer)
    def query_agent(request: AgentQuery) -> AgentAnswer:
        try:
            run = service.run(request.question, conversation_id=request.conversation_id, actor=request.user)
        except AgentExecutionError as error:
            logger.exception("Falló la corrida %s del agente", error.run_id)
            if isinstance(error.__cause__, RagConfigError):
                raise HTTPException(status_code=503, detail="El agente no está configurado todavía.") from error
            raise HTTPException(
                status_code=502,
                detail=f"El agente no pudo responder en este momento (referencia {error.run_id}). "
                "Inténtalo de nuevo en unos minutos.",
            ) from error
        except Exception as error:  # noqa: BLE001 - nunca se devuelve un stack trace crudo
            logger.exception("Error inesperado en el endpoint del agente")
            raise HTTPException(status_code=502, detail="El agente no pudo responder en este momento.") from error
        if run.status == STATUS_INVALID_QUESTION:
            raise HTTPException(status_code=422, detail=run.answer)
        return AgentAnswer(answer=run.answer, status=run.status, run_id=run.run_id, sources=run.sources,
                           conversation_id=run.conversation_id, memory=run.memory)

    return router

