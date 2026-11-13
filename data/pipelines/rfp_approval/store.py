"""Contrato de persistencia de la Parte 3 + implementación en memoria para pruebas. La versión PostgreSQL es `SqlRfpStore`
(services/api/app/rfp/repository.py). La verdad vive en la base de datos; el checkpointer solo guarda dónde quedó cada rama."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Protocol

from data.pipelines.rfp_response.store import InMemoryResponseStore

from . import config

SECTION_FIELDS = {"approval_status", "approver", "approved_at", "approval_comment", "approval_round", "approval_history", "escalated",
                  "approval_branch", "figures"}
TICKET_FIELDS = {"ceo_approval", "conflicts_log", "processing_error"}
SECTION_DEFAULTS = {"approval_status": config.APPROVAL_PENDING, "approver": None, "approved_at": None, "approval_comment": None,
                    "approval_round": 0, "approval_history": [], "escalated": False, "approval_branch": config.BRANCH_IDLE}


class ApprovalStore(Protocol):
    def get_part3_input(self, ticket_id: int) -> dict: ...  # {"status","handoff","sections":{dept:{...}},"ceo","conflicts_log","completed_at"}
    def open_approval(self, ticket_id: int, ceo: dict) -> None: ...
    def approval_update(self, ticket_id: int, department_id: str, **fields) -> None: ...
    def section_update(self, ticket_id: int, department_id: str, **fields) -> None: ...  # campos de la Parte 2 (regeneración)
    def ticket_update(self, ticket_id: int, **fields) -> None: ...
    def heartbeat(self, ticket_id: int, node: str) -> None: ...
    def end_work(self, ticket_id: int) -> None: ...
    def claim_close(self, ticket_id: int) -> bool: ...
    def save_final_document(self, ticket_id: int, document: dict) -> None: ...
    def complete_approval(self, ticket_id: int) -> None: ...
    def fail_approval(self, ticket_id: int, message: str) -> None: ...
    def record_event(self, ticket_id: int, event: dict) -> None: ...
    def list_events(self, ticket_id: int) -> list[dict]: ...


class InMemoryApprovalStore(InMemoryResponseStore):
    def __init__(self):
        super().__init__()
        self.events: dict[int, list[dict]] = {}
        self.documents: dict[int, dict] = {}

    def get_part3_input(self, ticket_id: int) -> dict:
        with self._lock:
            t = self.tickets[ticket_id]
            sections = {}
            for s in self.sections.get(ticket_id, []):
                sections[s["department_id"]] = {**copy.deepcopy(SECTION_DEFAULTS), **copy.deepcopy(s)}
            return copy.deepcopy({"status": t["status"], "handoff": t["handoff"], "part3_handoff": t.get("part3_handoff"),
                                  "sections": sections, "ceo": t.get("ceo_approval"), "conflicts_log": t.get("conflicts_log") or [],
                                  "completed_at": t.get("completed_at"), "processing_error": t["processing_error"]})

    def open_approval(self, ticket_id: int, ceo: dict) -> None:
        with self._lock:
            t = self.tickets[ticket_id]
            t.update(status=config.STATUS_AWAITING, processing_error=None, ceo_approval=copy.deepcopy(ceo), conflicts_log=[],
                     completed_at=None, closing=False)
            self.documents.pop(ticket_id, None)
            self._log(ticket_id, config.STATUS_AWAITING)
            for s in self.sections[ticket_id]:
                s.update(copy.deepcopy(SECTION_DEFAULTS))

    def approval_update(self, ticket_id: int, department_id: str, **fields) -> None:
        unknown = set(fields) - SECTION_FIELDS
        if unknown:
            raise ValueError(f"Campos de aprobación desconocidos: {sorted(unknown)}")
        self.section_update(ticket_id, department_id, **fields)

    def ticket_update(self, ticket_id: int, **fields) -> None:
        unknown = set(fields) - TICKET_FIELDS
        if unknown:
            raise ValueError(f"Campos de ticket desconocidos: {sorted(unknown)}")
        with self._lock:
            self.tickets[ticket_id].update(copy.deepcopy(fields))

    def end_work(self, ticket_id: int) -> None:
        pass

    def claim_close(self, ticket_id: int) -> bool:
        with self._lock:
            t = self.tickets[ticket_id]
            if t["status"] != config.STATUS_AWAITING or t.get("closing"):
                return False
            t["closing"] = True
            return True

    def save_final_document(self, ticket_id: int, document: dict) -> None:
        with self._lock:
            self.documents[ticket_id] = copy.deepcopy(document)

    def complete_approval(self, ticket_id: int) -> None:
        with self._lock:
            self.tickets[ticket_id].update(status=config.STATUS_DONE, completed_at=datetime.now(timezone.utc).isoformat(), processing_error=None)
            self._log(ticket_id, config.STATUS_DONE)

    def fail_approval(self, ticket_id: int, message: str) -> None:
        self._update(ticket_id, processing_error=message, closing=False)  # libera el cierre para poder reintentar

    def record_event(self, ticket_id: int, event: dict) -> None:
        with self._lock:
            events = self.events.setdefault(ticket_id, [])
            events.append({**copy.deepcopy(event), "seq": len(events) + 1})

    def list_events(self, ticket_id: int) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self.events.get(ticket_id, []))
