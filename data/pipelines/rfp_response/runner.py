"""Ejecuta la Parte 2 para UN ticket. Igual que en la Parte 1, la verdad vive en PostgreSQL: cada nodo deja un latido, un fallo se
registra con `fail_generation` (el ticket NO se queda mudo ni cambia a un estado final falso) y se puede reintentar.

Modos: `start` (desde analisis_completo), `resume` (retoma tras un fallo: conserva las secciones que ya terminaron) y
`regenerate` (descarta los borradores y empieza de nuevo)."""
from __future__ import annotations

import logging

from .agents import NotReady
from .graph import build_graph
from .store import ResponseStore

logger = logging.getLogger(__name__)


def default_llm():
    from data.pipelines.rag import complete

    return complete


def generate_ticket(ticket_id: int, store: ResponseStore, llm=None, *, mode: str = "start", graph=None) -> str:
    """Devuelve «completo» (todas pasaron), «revision_humana» (alguna agotó iteraciones), «no_listo» o «fallo». No lanza."""
    try:
        graph = graph or build_graph(llm or default_llm(), store)
        final = graph.invoke({"ticket_id": ticket_id, "mode": mode, "sections": [], "errors": []})
        return final.get("outcome", "fallo")
    except NotReady as exc:
        logger.warning("rfp_response: ticket %s no está listo: %s", ticket_id, exc)
        return "no_listo"
    except Exception as exc:  # noqa: BLE001 - corre en background: nadie más verá la excepción
        logger.exception("rfp_response: falló el ticket %s", ticket_id)
        try:
            store.fail_generation(ticket_id, f"{type(exc).__name__}: {str(exc)[:500]}")
        except Exception:  # noqa: BLE001
            logger.exception("rfp_response: no se pudo registrar el fallo del ticket %s", ticket_id)
        return "fallo"
