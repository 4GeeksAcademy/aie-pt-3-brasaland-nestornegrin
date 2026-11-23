"""Ejecuta el pipeline para UN ticket y mantiene la base de datos como fuente de verdad.

Dónde corre el trabajo async: en una `BackgroundTask` de FastAPI (mismo proceso, mismo API: el ticket exige «sin API nuevo»).
Cómo sigue siendo verdad el ticket si el job falla a mitad: el estado vive en PostgreSQL, no en el proceso. Cada nodo deja un
latido (`current_node`, `heartbeat_at`). Si el pipeline lanza una excepción, `fail()` guarda el error y el ticket NO se queda
mudo: la API lo expone como «falló» (y como «detenido» si el proceso murió sin avisar y el latido caduca), y se puede reintentar.
Un ticket nunca pasa a `analisis_completo` ni a `descartado` por un error: esos estados solo los escribe el pipeline al terminar.
"""
from __future__ import annotations

import logging

from .graph import build_graph
from .store import RfpStore

logger = logging.getLogger(__name__)


def default_llm():
    from data.pipelines.rag import complete  # el mismo modelo de generación del resto de la plataforma

    return complete


def process_ticket(ticket_id: int, store: RfpStore, llm=None, *, force: bool = False, graph=None) -> str:
    """Devuelve el resultado: «completo», «descartado» o «fallo». No lanza: un error de un ticket no afecta a los demás."""
    try:
        store.begin(ticket_id)
        graph = graph or build_graph(llm or default_llm(), store)
        final = graph.invoke({"ticket_id": ticket_id, "force": force, "findings": []})
        return final.get("outcome", "fallo")
    except Exception as exc:  # noqa: BLE001 - el job corre en background: nadie más va a ver la excepción
        logger.exception("rfp_intake: falló el ticket %s", ticket_id)
        try:
            store.fail(ticket_id, f"{type(exc).__name__}: {str(exc)[:300]}")
        except Exception:  # noqa: BLE001
            logger.exception("rfp_intake: no se pudo registrar el fallo del ticket %s", ticket_id)
        return "fallo"
