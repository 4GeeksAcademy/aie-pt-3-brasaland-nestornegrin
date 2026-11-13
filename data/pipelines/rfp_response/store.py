"""Contrato de persistencia de la Parte 2 + implementación en memoria para pruebas. La versión PostgreSQL es `SqlRfpStore`
(services/api/app/rfp/repository.py): una sola clase implementa ambas partes, así hay un único sitio donde viven los tickets."""
from __future__ import annotations

import copy
from typing import Protocol

from data.pipelines.rfp_intake.store import InMemoryRfpStore

from . import config


class ResponseStore(Protocol):
    def get_part2_input(self, ticket_id: int) -> dict: ...  # {"status","handoff","sections":{dept:{generation_status,...}},"processing_error"}
    def begin_generation(self, ticket_id: int, departments: list[str], resume: bool) -> None: ...
    def heartbeat(self, ticket_id: int, node: str) -> None: ...
    def section_update(self, ticket_id: int, department_id: str, **fields) -> None: ...
    def mark_evaluating(self, ticket_id: int) -> None: ...
    def complete_generation(self, ticket_id: int, status: str, part3_handoff: dict) -> None: ...
    def fail_generation(self, ticket_id: int, message: str) -> None: ...


class InMemoryResponseStore(InMemoryRfpStore):
    def __init__(self):
        super().__init__()
        self.status_log: list[tuple[int, str]] = []  # (ticket, estado) en el orden en que cambió

    def _log(self, ticket_id: int, status: str) -> None:
        if not self.status_log or self.status_log[-1] != (ticket_id, status):
            self.status_log.append((ticket_id, status))

    def get_part2_input(self, ticket_id: int) -> dict:
        with self._lock:
            t = self.tickets[ticket_id]
            return copy.deepcopy({"status": t["status"], "handoff": t["handoff"], "processing_error": t["processing_error"],
                                  "sections": {s["department_id"]: s for s in self.sections.get(ticket_id, [])}})

    def begin_generation(self, ticket_id: int, departments: list[str], resume: bool) -> None:
        with self._lock:
            t = self.tickets[ticket_id]
            t.update(status=config.STATUS_GENERATING, processing_error=None, part3_handoff=None, response_completed_at=None)
            self._log(ticket_id, config.STATUS_GENERATING)
            for s in self.sections[ticket_id]:
                if resume and s.get("generation_status") in config.SECTION_FINAL:
                    continue
                s.update(generation_status=config.SECTION_PENDING if s["department_id"] in departments else s.get("generation_status"),
                         iterations=0, needs_human_review=False, draft_content=None, evaluation_results=None, evaluation_history=[],
                         pending_items=[], generation_error=None)

    def section_update(self, ticket_id: int, department_id: str, **fields) -> None:
        with self._lock:
            sec = next(s for s in self.sections[ticket_id] if s["department_id"] == department_id)
            sec.update(copy.deepcopy(fields))

    def mark_evaluating(self, ticket_id: int) -> None:
        with self._lock:
            if self.tickets[ticket_id]["status"] == config.STATUS_GENERATING:
                self.tickets[ticket_id]["status"] = config.STATUS_EVALUATING
                self._log(ticket_id, config.STATUS_EVALUATING)

    def complete_generation(self, ticket_id: int, status: str, part3_handoff: dict) -> None:
        with self._lock:
            self.tickets[ticket_id].update(status=status, part3_handoff=copy.deepcopy(part3_handoff), processing_error=None,
                                           response_completed_at="done")
            self._log(ticket_id, status)

    def fail_generation(self, ticket_id: int, message: str) -> None:
        self._update(ticket_id, processing_error=message)
