"""Puntos de entrada de la Parte 3: `start` (abre las ramas de aprobación) y `resume` (reanuda SOLO la rama que decidió).

La respuesta humana se valida ANTES de tocar el checkpoint. Ninguna excepción escapa al proceso en segundo plano: un fallo se
registra en el ticket (`processing_error`) y se puede reintentar."""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any

from langgraph.types import Command

from data.pipelines.rfp_response.agents import NotReady

from . import config
from .checkpoint import build_checkpointer
from .graph import build_ceo_graph, build_department_graph, build_ticket_graph
from .schemas import InvalidDecision, validate_decision
from .store import ApprovalStore

logger = logging.getLogger(__name__)
_LOCKS: dict[int, threading.Lock] = defaultdict(threading.Lock)  # un `converge` a la vez por ticket (las ramas NO comparten candado)


def default_llm():
    from data.pipelines.rag import complete

    return complete


class ApprovalEngine:
    def __init__(self, store: ApprovalStore, llm: Any = None, checkpointer: Any = None):
        self.store = store
        self.llm = llm or default_llm()
        self.checkpointer = checkpointer if checkpointer is not None else build_checkpointer()
        self.department_graph = build_department_graph(store, self.llm, self.checkpointer)
        self.ceo_graph = build_ceo_graph(store, self.checkpointer)
        self.ticket_graph = build_ticket_graph(store, self.llm, self.checkpointer, self.department_graph, self.ceo_graph)

    @staticmethod
    def _cfg(ticket_id: int, department_id: str | None = None) -> dict:
        return {"configurable": {"thread_id": config.thread_id(ticket_id, department_id)}}

    def _graph_for(self, department_id: str):
        return self.ceo_graph if department_id == config.CEO_ID else self.department_graph

    def _converge(self, ticket_id: int, mode: str) -> None:
        with _LOCKS[ticket_id]:
            self.ticket_graph.invoke({"ticket_id": ticket_id, "mode": mode, "trace": []}, self._cfg(ticket_id))

    def status(self, ticket_id: int) -> str:
        return self.store.get_part3_input(ticket_id)["status"]

    # ---- puntos de entrada ------------------------------------------------------------------------------
    def start(self, ticket_id: int) -> str:
        """Abre la aprobación: pasa a esperando_aprobación y lanza una rama por departamento hasta su `interrupt`. No lanza."""
        try:
            self._converge(ticket_id, "start")
            return self.status(ticket_id)
        except NotReady as exc:
            logger.warning("rfp_approval: ticket %s no está listo: %s", ticket_id, exc)
            return "no_listo"
        except Exception as exc:  # noqa: BLE001
            return self._fail(ticket_id, exc)
        finally:
            self._end(ticket_id)

    def pending(self, ticket_id: int, department_id: str) -> bool:
        """¿Hay de verdad una interrupción pendiente en el checkpoint de esa rama?"""
        state = self._graph_for(department_id).get_state(self._cfg(ticket_id, department_id))
        return "await_approval" in (state.next or ())

    def validate(self, ticket_id: int, raw: dict) -> Any:
        """Valida la respuesta humana contra el estado actual. Lanza `InvalidDecision`; no modifica nada."""
        department_id = str(raw.get("department_id", ""))
        inp = self.store.get_part3_input(ticket_id)
        if inp["status"] != config.STATUS_AWAITING:
            raise InvalidDecision(f"El ticket está en «{inp['status']}», no en {config.STATUS_AWAITING}.", "not_awaiting")
        if department_id == config.CEO_ID:
            ceo = inp["ceo"] or {}
            waiting, escalated, draft = bool(ceo.get("required")) and ceo.get("branch") == config.BRANCH_WAITING, False, ""
        elif department_id in inp["sections"]:
            section = inp["sections"][department_id]
            waiting, escalated, draft = section["approval_branch"] == config.BRANCH_WAITING, bool(section.get("escalated")), section.get("draft_content") or ""
        else:
            raise InvalidDecision(f"«{department_id}» no es un departamento activo de este ticket.", "department")
        decision = validate_decision(raw, department_id=department_id, waiting=waiting, escalated=escalated, draft_text=draft)
        if waiting and not self.pending(ticket_id, department_id):
            raise InvalidDecision(f"«{department_id}» no tiene una interrupción pendiente en su checkpoint.", "not_waiting")
        return decision

    def resume(self, ticket_id: int, raw: dict) -> str:
        """Reanuda la rama del departamento que decidió (checkpoint `rfp-{ticket}:{dept}`), sin reiniciar el flujo ni tocar a los demás.
        Lanza `InvalidDecision` ANTES de modificar nada; cualquier otro fallo queda registrado en el ticket."""
        decision = self.validate(ticket_id, raw)
        try:
            self.store.heartbeat(ticket_id, f"resume:{decision.department_id}")
            self.store.ticket_update(ticket_id, processing_error=None)
            self._graph_for(decision.department_id).invoke(Command(resume=decision.model_dump()), self._cfg(ticket_id, decision.department_id))
            self._converge(ticket_id, "converge")
            return self.status(ticket_id)
        except Exception as exc:  # noqa: BLE001
            return self._fail(ticket_id, exc)
        finally:
            self._end(ticket_id)

    def retry(self, ticket_id: int) -> str:
        """Reintenta la convergencia (p. ej. tras un fallo del sintetizador) sin pedir de nuevo ninguna aprobación."""
        try:
            self.store.ticket_update(ticket_id, processing_error=None)
            self._converge(ticket_id, "converge")
            return self.status(ticket_id)
        except Exception as exc:  # noqa: BLE001
            return self._fail(ticket_id, exc)
        finally:
            self._end(ticket_id)

    # ---- internos ---------------------------------------------------------------------------------------
    def _fail(self, ticket_id: int, exc: Exception) -> str:
        logger.exception("rfp_approval: falló el ticket %s", ticket_id)
        try:
            self.store.fail_approval(ticket_id, f"{type(exc).__name__}: {str(exc)[:500]}")
        except Exception:  # noqa: BLE001
            logger.exception("rfp_approval: no se pudo registrar el fallo del ticket %s", ticket_id)
        return "fallo"

    def _end(self, ticket_id: int) -> None:
        try:
            self.store.end_work(ticket_id)
        except Exception:  # noqa: BLE001
            logger.exception("rfp_approval: no se pudo cerrar el latido del ticket %s", ticket_id)
