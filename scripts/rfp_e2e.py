"""Ruta E2E REPRODUCIBLE del Hito 9: una RFP recorre las tres partes (recepción → generación → aprobación y cierre) con
aprobaciones humanas SIMULADAS por `resume` programático, sin clics en la UI.

    uv run python -m scripts.rfp_e2e                      # modelo simulado (offline, determinista): es lo que corre el test
    uv run python -m scripts.rfp_e2e --real               # modelo real (necesita GENERATION_MODEL… como el asistente RAG)
    uv run python -m scripts.rfp_e2e ruta.pdf --real      # otra RFP

Guion de aprobaciones simuladas: Training pide cambios una vez (vuelve a SU generador y vuelve a pausarse), las demás ramas aprueban
mientras tanto, y si la RFP supera 50.000 USD/año la CEO aprueba al final. Imprime Markdown listo para el PR.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "pipelines"))

from data.pipelines.rfp_approval import ApprovalEngine, InMemoryApprovalStore, build_checkpointer  # noqa: E402
from data.pipelines.rfp_intake import process_ticket  # noqa: E402
from data.pipelines.rfp_response import generate_ticket  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "rfp"
OWNERS = {"marketing": "Camila Ospina", "operaciones": "Felipe Guerrero", "procurement": "Lucía Fernández", "training": "Jake Morrison",
          "ceo": "Mariana Restrepo"}


def run(pdf: Path | None = None, *, real: bool = False, checkpoint_dir: Path | None = None, out=print) -> dict:
    pdf = pdf or FIXTURES / "brasaland-request-1.pdf"
    if real:
        from data.pipelines.rag import complete as llm
    else:
        from rfp_approval_support import ThreePartModel  # noqa: PLC0415 - solo en modo simulado

        llm = ThreePartModel()
    store, steps = InMemoryApprovalStore(), []
    checkpoint = (checkpoint_dir or Path(tempfile.mkdtemp(prefix="rfp-e2e-"))) / "checkpoints.sqlite"
    engine = ApprovalEngine(store, llm, build_checkpointer(checkpoint))

    def decide(dept: str, action: str = "approve", comment: str = "") -> None:
        status = engine.resume(1, {"department_id": dept, "action": action, "approver": OWNERS[dept], "comment": comment})
        steps.append({"department": dept, "action": action, "comment": comment, "ticket_status": status})
        out(f"- **{OWNERS[dept]}** ({dept}) → `{action}`{f' — «{comment}»' if comment else ''} · ticket: `{status}`")

    store.add(1, str(pdf), pdf.name)
    out(f"# E2E · {pdf.name}\n\n## Parte 1 — recepción\n")
    out(f"- resultado: `{process_ticket(1, store, llm)}` · estado: `{store.get_ticket(1)['status']}`")
    meta = store.get_ticket(1)["metadata"]
    out(f"- cliente: {meta['client_name']} · {meta['service_type']} · presupuesto: {meta['budget_range'] or 'no indicado'}")
    departments = [w["department_id"] for w in store.get_ticket(1)["handoff"]["workstreams"]]
    out(f"- departamentos activos: {', '.join(departments)}\n\n## Parte 2 — generación y evaluación\n")
    out(f"- resultado: `{generate_ticket(1, store, llm)}` · estado: `{store.get_ticket(1)['status']}`")
    for s in store.sections[1]:
        out(f"- {s['department_id']}: {s['generation_status']} en {s['iterations']} iteración(es)")
    out("\n## Parte 3 — aprobación humana (simulada con resume)\n")
    out(f"- apertura: `{engine.start(1)}` · ramas pausadas: {', '.join(d for d in departments if engine.pending(1, d))}")
    if "training" in departments:
        decide("training", "request_changes", "Indica quién certifica la receta de autor y en cuánto tiempo.")
        out(f"  - training volvió a SU generador y se pausó de nuevo (ronda 2); las demás ramas siguen pausadas: "
            f"{', '.join(d for d in departments if engine.pending(1, d))}")
    for d in departments:
        decide(d)
    if store.get_part3_input(1)["ceo"]["required"]:
        out(f"- la propuesta supera 50.000 USD/año → la CEO tiene la última pausa (`ceo-threshold`)")
        decide("ceo")
    state = store.get_part3_input(1)
    out(f"\n## Resultado\n\n- estado final: `{state['status']}` · conflictos: "
        f"{', '.join(f'{c['trigger_id']} ({c['status']})' for c in state['conflicts_log']) or 'ninguno'}")
    doc = store.documents.get(1)
    if doc:
        out(f"\n<details><summary>Documento final ({len(doc['content'])} caracteres)</summary>\n\n```markdown\n{doc['content']}```\n</details>")
    events = store.list_events(1)
    out(f"\n<details><summary>Trazabilidad ({len(events)} eventos)</summary>\n\n| # | parte | agente | nodo |\n|---|---|---|---|")
    for e in events:
        out(f"| {e['seq']} | {e['part']} | {e['agent']} | {e['node']} |")
    out("\n</details>")
    return {"status": state["status"], "document": doc, "events": events, "steps": steps, "state": state}


def main(argv: list[str]) -> int:
    real = "--real" in argv
    paths = [Path(a) for a in argv if not a.startswith("--")]
    result = run(paths[0] if paths else None, real=real)
    return 0 if result["status"] == "terminado" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
