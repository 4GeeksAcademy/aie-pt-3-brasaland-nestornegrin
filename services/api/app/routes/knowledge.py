"""Endpoint de consulta a la base de conocimiento de Brasaland (Hito 7 — RAG).

`POST /knowledge/query` recibe `{"question": "..."}` y responde `{"answer": "..."}` con el texto que redacta el
modelo de generación. Valida la petición y llama a `query()`, que aplica los guardrails del agente y delega la recuperación en `data/pipelines/rag.py`. Nunca devuelve chunks, listas de resultados ni puntuaciones de
similitud (eso queda en el log del servidor, para depurar).

Este router no impone autenticación por sí solo; la API lo monta con `Depends(get_current_user)` (auditoría OWASP A01:
antes era público y permitía consumir el modelo y la base de conocimiento sin sesión).
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
from data.pipelines.rag import retrieve  # noqa: E402
from services.agent.guardrails import patterns, policy, sensitive  # noqa: E402
from services.agent.guardrails.text import views  # noqa: E402
from services.agent.guardrails.text import detect_language  # noqa: E402
from services.agent.guardrails.output_guard import check_output  # noqa: E402
from services.agent.guardrails.prompts import secure_generate_answer  # noqa: E402
from data.process.rag_config import RagConfigError  # noqa: E402

logger = logging.getLogger(__name__)

Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class KnowledgeQuery(BaseModel):
    question: Question


class KnowledgeAnswer(BaseModel):
    answer: str


def query(question: str) -> str:
    """Consulta al RAG con las defensas del agente (NIST Protect · OWASP A03): guardrail de entrada, contexto recuperado
    saneado y delimitado como DATO (`<datos>`, inyección indirecta) y guardrail de salida. Antes este endpoint usaba el
    prompt básico de `data/pipelines/rag.py`, sin ninguna de las tres."""
    # Solo los guardrails de SEGURIDAD del agente (cambiar las instrucciones, pedir datos confidenciales): el asistente de
    # entrenamiento sí responde sobre recetas y estándares, así que no se aplican los de dominio/contenido del agente de gerentes.
    text_views = views(question)
    if patterns.match_family(text_views, patterns.JAILBREAK_FAMILIES):
        reason, refusal = "override", "override"
    elif sensitive.sensitive_request(question):
        reason, refusal = "sensitive", "sensitive"
    else:
        reason = refusal = None
    if refusal:
        logger.warning("knowledge: pregunta bloqueada por el guardrail de entrada (%s)", reason)
        return policy.REFUSALS[refusal]["en" if detect_language(question) == "en" else "es"]
    answer = secure_generate_answer(question, retrieve(question))
    return check_output(answer, question=question, language="en" if detect_language(question) == "en" else "es").answer


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
