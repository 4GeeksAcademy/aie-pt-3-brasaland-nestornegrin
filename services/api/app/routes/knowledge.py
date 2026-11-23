"""Endpoint de consulta a la base de conocimiento de Brasaland (Hito 7 — RAG).

`POST /knowledge/query` recibe `{"question": "..."}` y responde `{"answer": "..."}` con el texto que redacta el
modelo de generación. Este router NO contiene lógica de recuperación ni de generación: solo valida la petición y
llama a `query()` de `data/pipelines/rag.py`. Nunca devuelve chunks, listas de resultados ni puntuaciones de
similitud (eso queda en el log del servidor, para depurar).

El endpoint no exige sesión: el ticket define solo el cuerpo de petición y de respuesta, y así lo puede consumir
cualquier cliente (la UI del backoffice, un agente posterior, curl). Si se expone fuera de la red interna conviene
protegerlo con `get_current_user` (ver docs/rag/rag-design.md).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StringConstraints

# `data/` vive en la raíz del monorepo, no en services/api: se añade la raíz al path (mismo patrón que usa
# app/incidents/models.py para importar packages/shared).
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from data.pipelines.rag import query  # noqa: E402
from data.process.rag_config import RagConfigError  # noqa: E402

logger = logging.getLogger(__name__)

Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class KnowledgeQuery(BaseModel):
    question: Question


class KnowledgeAnswer(BaseModel):
    answer: str


def create_router(prefix: str = "/knowledge") -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["knowledge"])

    # Función síncrona a propósito: FastAPI la ejecuta en un hilo y no bloquea el bucle de eventos mientras
    # se espera a Qdrant y al modelo.
    @router.post("/query", response_model=KnowledgeAnswer)
    def query_knowledge(request: KnowledgeQuery) -> KnowledgeAnswer:
        try:
            answer = query(request.question)
        except RagConfigError as error:
            logger.error("RAG sin configurar: %s", error)
            raise HTTPException(status_code=503, detail="El asistente no está configurado todavía.") from error
        except Exception as error:  # noqa: BLE001 - Qdrant o el LLM caídos; el detalle va al log, no al cliente
            logger.exception("Falló la consulta a la base de conocimiento")
            raise HTTPException(
                status_code=502,
                detail="El asistente no pudo responder en este momento. Inténtalo de nuevo en unos minutos.",
            ) from error
        return KnowledgeAnswer(answer=answer)

    return router
