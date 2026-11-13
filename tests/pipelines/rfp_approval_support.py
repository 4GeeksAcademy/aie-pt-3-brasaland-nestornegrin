"""Utilidades de las pruebas de la Parte 3: un modelo simulado para las tres partes, un ticket sembrado y aprobaciones simuladas."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rfp_response_support import ScriptedResponseModel  # noqa: E402
from rfp_support import PDF_FORMAL, PDF_INFORMAL, ScriptedRfpModel  # noqa: E402

from data.pipelines.rfp_approval import ApprovalEngine, InMemoryApprovalStore, build_checkpointer  # noqa: E402
from data.pipelines.rfp_intake import process_ticket  # noqa: E402
from data.pipelines.rfp_response import generate_ticket  # noqa: E402

OWNERS = {"marketing": "Camila Ospina", "operaciones": "Felipe Guerrero", "procurement": "Lucía Fernández", "training": "Jake Morrison",
          "ceo": "Mariana Restrepo"}


class ThreePartModel:
    """Un solo modelo simulado para las Partes 1, 2 y 3 (los prompts de la Parte 2 van al guion de la Parte 2)."""

    def __init__(self):
        self.part1, self.part2 = ScriptedRfpModel(), ScriptedResponseModel()

    def __call__(self, messages):
        system = messages[0]["content"]
        return (self.part2 if system.startswith(("Eres el agente GENERADOR", "Eres el agente EVALUADOR")) else self.part1)(messages)


def seed(store: InMemoryApprovalStore, model: ThreePartModel, pdf: Path = PDF_FORMAL, ticket_id: int = 1) -> int:
    """Corre las Partes 1 y 2 de verdad (con el modelo simulado) y deja el ticket listo para la Parte 3."""
    store.add(ticket_id, str(pdf), pdf.name)
    assert process_ticket(ticket_id, store, model) == "completo"
    assert generate_ticket(ticket_id, store, model) in ("completo", "revision_humana")
    return ticket_id


def engine_for(store, model, tmp_path, name: str = "cp.sqlite") -> ApprovalEngine:
    return ApprovalEngine(store, model, build_checkpointer(tmp_path / name))


def decide(engine: ApprovalEngine, ticket_id: int, department_id: str, action: str = "approve", comment: str = "", **extra) -> str:
    return engine.resume(ticket_id, {"department_id": department_id, "action": action, "approver": OWNERS[department_id],
                                     "comment": comment, **extra})


def approve_all(engine: ApprovalEngine, ticket_id: int, departments=("marketing", "operaciones", "procurement", "training")) -> None:
    for d in departments:
        decide(engine, ticket_id, d)
