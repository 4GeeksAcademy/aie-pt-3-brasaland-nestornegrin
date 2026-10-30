"""Fase 2 del RAG de Brasaland: recuperar contexto y generar la respuesta.

Tres funciones, cada una con una única responsabilidad:

    retrieve()         busca en Qdrant, descarta lo que no llega al umbral y devuelve los payloads supervivientes.
    generate_answer()  arma el prompt (voz y audiencia del BRIEFING) y llama al modelo de generación.
    query()            es literalmente `retrieve()` + `generate_answer()`; es lo único que llaman los consumidores
                       externos (el endpoint FastAPI). Un agente posterior puede llamar a las dos piezas por separado.

La respuesta final SIEMPRE la redacta el modelo a partir del contexto recuperado: nunca se devuelve el resultado
crudo de la búsqueda vectorial.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from data.process.rag import embed
from data.process.rag_config import (
    COLLECTION_NAME,
    DEFAULT_K,
    DEFAULT_MIN_SCORE,
    get_generation_client,
    get_qdrant_client,
    load_settings,
)

logger = logging.getLogger(__name__)

# Voz y audiencia definidas en el BRIEFING del Hito 7: el asistente responde "como lo haría un vendedor entrenado" a
# gerentes de local, clientes y empleados nuevos de Brasaland (Colombia y Florida), con datos correctos y sin inventar.
SYSTEM_PROMPT = """Eres el asistente de conocimiento de Brasaland, una cadena de restaurantes a la brasa con \
locales en Colombia y Florida. Respondes como lo haría un vendedor entrenado del equipo: con seguridad, de forma \
cercana y directa, y con los datos correctos. Hablas con gerentes de local, clientes y personal nuevo.

Reglas obligatorias:
1. Usa ÚNICAMENTE la información del bloque CONTEXTO. No uses conocimiento externo ni supongas nada que no esté ahí.
2. Datos numéricos: cada número, porcentaje, monto, plazo o cantidad de tu respuesta debe aparecer tal cual en el \
CONTEXTO. Mantén los montos en USD y en COP como están escritos; no conviertas monedas.
3. Si el CONTEXTO está vacío o no contiene la respuesta, di claramente que no tienes información suficiente en la \
base de conocimiento de Brasaland para responder eso. Nunca inventes datos de la empresa. En ese caso responde en \
una o dos frases, sin mencionar "contexto", "bloque" ni fragmentos, sin pedir al usuario que te comparta \
documentos y sin línea de "Fuente".
4. Alérgenos: nunca digas que algo es "sin riesgo" ni garantices cero riesgo de contaminación cruzada; sigue \
literalmente la redacción del CONTEXTO y comunica las advertencias que incluya.
5. Responde en español, de forma breve y clara (unas pocas frases o una lista corta).
6. Si usaste información del CONTEXTO, termina con una línea "Fuente: <documento> — <sección>" por cada fuente que \
utilizaste, con los nombres exactos que aparecen entre corchetes en el CONTEXTO, sin corchetes ni negritas en esa \
línea. Revisa la ortografía antes de responder."""

NO_CONTEXT_MARKER = "(vacío: no se recuperó ningún fragmento relevante de la base de conocimiento)"


@dataclass(frozen=True)
class ScoredChunk:
    """Resultado interno de la búsqueda: el payload y su puntuación de similitud (solo para depurar y evaluar)."""

    score: float
    payload: dict


# --------------------------------------------------------------------------------------------------------------
# Recuperación
# --------------------------------------------------------------------------------------------------------------
def search_scored(
    query: str,
    *,
    k: int = DEFAULT_K,
    client=None,
    embed_fn: Callable[[str], list[float]] | None = None,
) -> list[ScoredChunk]:
    """Los `k` vecinos más cercanos con su puntuación, SIN aplicar umbral. Uso interno: `retrieve()` filtra por
    umbral y la evaluación (`scripts/evaluate_rag.py`) necesita las puntuaciones para calibrarlo."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("La consulta no puede estar vacía.")
    if k < 1:
        raise ValueError("k debe ser al menos 1.")

    embed_fn = embed_fn if embed_fn is not None else embed  # la MISMA embed() que usa la indexación
    client = client if client is not None else get_qdrant_client()
    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=embed_fn(query),
        limit=k,
        with_payload=True,
    )
    return [ScoredChunk(score=float(point.score), payload=dict(point.payload or {})) for point in response.points]


def retrieve(
    query: str,
    *,
    k: int = DEFAULT_K,
    min_score: float | None = None,
    client=None,
    embed_fn: Callable[[str], list[float]] | None = None,
) -> list[dict]:
    """Recupera los payloads de los chunks más relevantes para `query`.

    Embebe la consulta, busca los `k` vecinos más cercanos en Qdrant y DESCARTA los que no alcanzan `min_score`
    (similitud coseno): puede devolver menos de `k` resultados, o ninguno. Devuelve dicts con el payload (no objetos
    del SDK ni puntuaciones; estas solo se registran en el log del servidor)."""
    threshold = min_score if min_score is not None else _default_min_score()
    scored = search_scored(query, k=k, client=client, embed_fn=embed_fn)
    survivors = [item for item in scored if item.score >= threshold]
    logger.info(
        "retrieve: %d/%d chunks sobre el umbral %.3f; puntuaciones=%s",
        len(survivors),
        len(scored),
        threshold,
        [round(item.score, 3) for item in scored],
    )
    return [dict(item.payload) for item in survivors]


def _default_min_score() -> float:
    """Umbral por defecto: `RAG_MIN_SCORE` si está definido, o el valor calibrado. Si falta configuración de
    modelos no se rompe aquí (la búsqueda ya lo hará con un mensaje claro)."""
    try:
        return load_settings().min_score
    except Exception:  # noqa: BLE001 - la configuración incompleta se reporta al usar los clientes
        return DEFAULT_MIN_SCORE


# --------------------------------------------------------------------------------------------------------------
# Generación
# --------------------------------------------------------------------------------------------------------------
def format_context(context: list[dict]) -> str:
    """Bloque CONTEXTO del prompt: cada chunk con su fuente entre corchetes, para que la respuesta sea trazable."""
    if not context:
        return NO_CONTEXT_MARKER
    return "\n\n".join(
        f"[{item.get('source_document', 'desconocido')} — {item.get('section', 'sin sección')}]\n{item.get('text', '')}"
        for item in context
    )


def build_messages(question: str, context: list[dict]) -> list[dict]:
    """Mensajes para el modelo de chat: reglas de voz y audiencia (system) + contexto y pregunta (user)."""
    user_prompt = f"CONTEXTO:\n{format_context(context)}\n\nPREGUNTA:\n{question.strip()}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


class EmptyCompletionError(RuntimeError):
    """El modelo de generación devolvió una respuesta vacía incluso tras reintentar."""


# Algunos modelos de razonamiento del gateway devuelven `content=None` de forma intermitente (gastan la respuesta
# "pensando"). Se reintenta una vez; si sigue vacía se lanza un error claro en vez de devolver un texto en blanco.
EMPTY_COMPLETION_ATTEMPTS = 2


def complete(messages: list[dict]) -> str:
    """Llamada al modelo de generación (`GENERATION_MODEL`, distinto del de embeddings). Temperatura 0: aquí
    se busca fidelidad al contexto, no creatividad. Nunca devuelve una cadena vacía: reintenta y, si no hay
    contenido, lanza `EmptyCompletionError`."""
    settings = load_settings()
    client = get_generation_client()
    for attempt in range(1, EMPTY_COMPLETION_ATTEMPTS + 1):
        response = client.chat.completions.create(
            model=settings.generation_model,
            messages=messages,
            temperature=0.0,
        )
        content = (response.choices[0].message.content or "").strip()
        if content:
            return content
        logger.warning("complete: respuesta vacía del modelo %s (intento %d/%d)",
                       settings.generation_model, attempt, EMPTY_COMPLETION_ATTEMPTS)
    raise EmptyCompletionError("El modelo de generación devolvió una respuesta vacía.")


def generate_answer(
    question: str,
    context: list[dict],
    *,
    complete_fn: Callable[[list[dict]], str] | None = None,
) -> str:
    """Arma el prompt y llama al LLM de generación. Está separada de `retrieve()` a propósito: un agente posterior
    (LangGraph) podrá llamar a `retrieve()` y a `generate_answer()` como pasos distintos, sin ejecutar la recuperación
    dos veces ni envolver el monolito de `query()`.

    Con `context` vacío el modelo recibe la instrucción de decir que no tiene información suficiente."""
    if not isinstance(question, str) or not question.strip():
        raise ValueError("La pregunta no puede estar vacía.")
    complete_fn = complete_fn if complete_fn is not None else complete
    return complete_fn(build_messages(question, context))


# --------------------------------------------------------------------------------------------------------------
# Punto de entrada
# --------------------------------------------------------------------------------------------------------------
def query(question: str) -> str:
    """Responde una pregunta en lenguaje natural: `retrieve()` + `generate_answer()`. Devuelve solo el texto
    redactado por el modelo (nunca chunks, listas ni puntuaciones)."""
    context = retrieve(question)
    return generate_answer(question, context)
