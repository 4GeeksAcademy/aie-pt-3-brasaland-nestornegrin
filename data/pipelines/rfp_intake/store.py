"""Contrato de persistencia del pipeline. El pipeline NO conoce SQL ni FastAPI: recibe un `RfpStore`.

La implementación real (PostgreSQL/Supabase vía SQLModel) vive en `services/api/app/rfp/repository.py`; aquí solo está el
contrato y una implementación en memoria para pruebas y para el script de humo. Así `data/pipelines/` no depende de `services/`.
"""
from __future__ import annotations

import copy
import threading
from typing import Protocol

from .departments import STATUS_ANALYZING, STATUS_COMPLETE, STATUS_DISCARDED


class RfpStore(Protocol):
    def get_ticket(self, ticket_id: int) -> dict: ...  # {"ticket_id","status","raw_pdf_path","markdown","original_filename"}
    def begin(self, ticket_id: int) -> None: ...  # status=analizando, borra el error previo, suma un intento
    def heartbeat(self, ticket_id: int, node: str) -> None: ...  # latido: en qué nodo va el pipeline
    def save_markdown(self, ticket_id: int, markdown: str) -> None: ...
    def save_classification(self, ticket_id: int, classification: dict) -> None: ...
    def mark_discarded(self, ticket_id: int, reason: str, classification: dict | None) -> None: ...
    def save_metadata(self, ticket_id: int, metadata: dict, readability: dict, rfp_id: str) -> None: ...
    def complete(self, ticket_id: int, sections: list[dict], handoff: dict, summary: dict, departments_needed: list[str]) -> None: ...
    def fail(self, ticket_id: int, message: str) -> None: ...  # el ticket sigue «analizando» pero con el error registrado


class InMemoryRfpStore:
    """Misma semántica que la implementación SQL, sin base de datos. Seguro entre hilos (los workers corren en paralelo)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.tickets: dict[int, dict] = {}
        self.sections: dict[int, list[dict]] = {}
        self.heartbeats: list[tuple[int, str]] = []

    def add(self, ticket_id: int, raw_pdf_path: str, original_filename: str = "rfp.pdf") -> None:
        self.tickets[ticket_id] = {"ticket_id": ticket_id, "status": STATUS_ANALYZING, "raw_pdf_path": raw_pdf_path,
                                   "original_filename": original_filename, "markdown": None, "attempts": 0,
                                   "processing_error": None, "discard_reason": None, "classification": None,
                                   "metadata": None, "readability": None, "rfp_id": None, "handoff": None, "summary": None,
                                   "departments_needed": []}

    def get_ticket(self, ticket_id: int) -> dict:
        with self._lock:
            return copy.deepcopy(self.tickets[ticket_id])

    def _update(self, ticket_id: int, **fields) -> None:
        with self._lock:
            self.tickets[ticket_id].update(fields)

    def begin(self, ticket_id: int) -> None:
        with self._lock:
            t = self.tickets[ticket_id]
            t.update(status=STATUS_ANALYZING, processing_error=None, discard_reason=None, attempts=t["attempts"] + 1)

    def heartbeat(self, ticket_id: int, node: str) -> None:
        with self._lock:
            self.heartbeats.append((ticket_id, node))

    def save_markdown(self, ticket_id: int, markdown: str) -> None:
        self._update(ticket_id, markdown=markdown)

    def save_classification(self, ticket_id: int, classification: dict) -> None:
        self._update(ticket_id, classification=classification)

    def mark_discarded(self, ticket_id: int, reason: str, classification: dict | None) -> None:
        self._update(ticket_id, status=STATUS_DISCARDED, discard_reason=reason, classification=classification)

    def save_metadata(self, ticket_id: int, metadata: dict, readability: dict, rfp_id: str) -> None:
        self._update(ticket_id, metadata=metadata, readability=readability, rfp_id=rfp_id)

    def complete(self, ticket_id: int, sections: list[dict], handoff: dict, summary: dict, departments_needed: list[str]) -> None:
        with self._lock:
            self.sections[ticket_id] = copy.deepcopy(sections)
            self.tickets[ticket_id].update(status=STATUS_COMPLETE, handoff=copy.deepcopy(handoff), summary=copy.deepcopy(summary),
                                           departments_needed=list(departments_needed), processing_error=None)

    def fail(self, ticket_id: int, message: str) -> None:
        self._update(ticket_id, processing_error=message)
