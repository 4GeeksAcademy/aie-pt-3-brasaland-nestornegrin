"""Grafo LangGraph DEDICADO `rfp_intake` (no se mezcla con el grafo CX / knowledge-agent).

    START → convert → classify ──(no es RFP)──→ discard → END
                          │
                          └─(RFP) → measure → extract_metadata → orchestrate ──Send×N──→ worker ─┐
                                                                                (uno por departamento, en paralelo)
                                                                              synthesize ←────────┘ → END

Patrón orchestrator-worker-synthesizer: el orquestador DECIDE qué departamentos aplican y qué extractos necesita cada uno; los
workers corren en paralelo (API `Send`) cada uno con SU contexto; el synthesizer consolida y deja el ticket en `analisis_completo`
con el contrato de handoff para la Parte 2. Los routers HTTP solo disparan este grafo: no contienen lógica de agentes.
"""
from __future__ import annotations

import logging
import operator
from pathlib import Path
from typing import Annotated, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from . import agents
from .convert import ConversionError, pdf_to_markdown
from .readability_metrics import measure
from .schemas import Finding, Plan, RfpMetadata
from .store import RfpStore

logger = logging.getLogger(__name__)

NODE_CONVERT, NODE_CLASSIFY, NODE_DISCARD, NODE_MEASURE = "convert", "classify", "discard", "measure"
NODE_METADATA, NODE_ORCHESTRATE, NODE_WORKER, NODE_SYNTHESIZE = "extract_metadata", "orchestrate", "worker", "synthesize"
NODE_NAMES = (NODE_CONVERT, NODE_CLASSIFY, NODE_DISCARD, NODE_MEASURE, NODE_METADATA, NODE_ORCHESTRATE, NODE_WORKER, NODE_SYNTHESIZE)
MIN_WORDS = 15  # por debajo de esto no hay nada que clasificar


class IntakeState(TypedDict, total=False):
    ticket_id: int
    force: bool  # un humano decidió que SÍ es una RFP (falso negativo del clasificador): se salta la decisión
    markdown: str
    discard_reason: str
    classification: dict
    readability: dict
    metadata: dict
    plan: dict
    findings: Annotated[list[dict], operator.add]  # cada worker añade el suyo (reducer para la ejecución en paralelo)
    outcome: str  # descartado | completo


def build_graph(llm: agents.Llm, store: RfpStore, *, converter: Callable[[str | Path], object] = pdf_to_markdown,
                measure_fn: Callable[[str], dict] = measure):
    def tracked(name: str, fn):
        def run(state):
            store.heartbeat(state["ticket_id"], name)  # latido: permite saber en qué nodo está (o murió) un ticket
            return fn(state)
        return run

    def convert(state: IntakeState) -> dict:
        ticket = store.get_ticket(state["ticket_id"])
        try:
            markdown = converter(ticket["raw_pdf_path"]).markdown  # type: ignore[attr-defined]
        except ConversionError as exc:  # PDF ilegible: ticket `descartado` con el motivo (nunca un fallo silencioso)
            return {"discard_reason": f"Documento ilegible: {exc}", "outcome": "descartado"}
        store.save_markdown(state["ticket_id"], markdown)
        return {"markdown": markdown}

    def classify(state: IntakeState) -> dict:
        if state.get("outcome") == "descartado":
            return {}
        markdown = state["markdown"]
        words = len(markdown.split())
        if words < MIN_WORDS:
            return {"discard_reason": f"Documento con muy poco texto ({words} palabras): no hay nada que analizar.", "outcome": "descartado"}
        if state.get("force"):
            classification = {"is_rfp": True, "forced_by_user": True, "reasons": ["Marcada como RFP por una persona (falso negativo)."]}
            store.save_classification(state["ticket_id"], classification)
            return {"classification": classification}
        result = agents.classify(llm, markdown)
        valid, why = agents.decide_rfp(result)
        classification = {**result.model_dump(), "decision": "rfp" if valid else "descartado", "decision_reason": why}
        store.save_classification(state["ticket_id"], classification)
        return {"classification": classification} if valid else {"classification": classification, "discard_reason": why, "outcome": "descartado"}

    def route_after_classify(state: IntakeState) -> str:
        return NODE_DISCARD if state.get("outcome") == "descartado" else NODE_MEASURE

    def discard(state: IntakeState) -> dict:
        store.mark_discarded(state["ticket_id"], state["discard_reason"], state.get("classification"))
        return {"outcome": "descartado"}

    def measure_node(state: IntakeState) -> dict:
        return {"readability": measure_fn(state["markdown"])}

    def extract_metadata(state: IntakeState) -> dict:
        meta = agents.extract_metadata(llm, state["markdown"])
        reference = meta.reference or f"RFP-{state['ticket_id']:05d}"
        store.save_metadata(state["ticket_id"], meta.model_dump(), state["readability"], reference)
        return {"metadata": meta.model_dump()}

    def orchestrate(state: IntakeState) -> dict:
        plan = agents.build_plan(llm, state["markdown"], RfpMetadata.model_validate(state["metadata"]))
        return {"plan": plan.model_dump()}

    def fan_out(state: IntakeState) -> list[Send]:
        """Un worker por departamento activo, cada uno con metadatos + SUS extractos (no el estado completo)."""
        return [Send(NODE_WORKER, {"ticket_id": state["ticket_id"], "markdown": state["markdown"], "metadata": state["metadata"],
                                   "assignment": a}) for a in state["plan"]["assignments"]]

    def worker(payload: dict) -> dict:
        a = payload["assignment"]
        store.heartbeat(payload["ticket_id"], f"{NODE_WORKER}:{a['department_id']}")
        finding = agents.run_worker(llm, a["department_id"], RfpMetadata.model_validate(payload["metadata"]), a["excerpts"],
                                    payload["markdown"], a.get("reason", ""))
        return {"findings": [finding.model_dump()]}

    def synthesize(state: IntakeState) -> dict:
        metadata, plan = RfpMetadata.model_validate(state["metadata"]), Plan.model_validate(state["plan"])
        findings = [Finding.model_validate(f) for f in state["findings"]]
        summary = agents.summarize(llm, metadata, findings)
        ticket = store.get_ticket(state["ticket_id"])
        rfp_id = ticket.get("rfp_id") or metadata.reference or f"RFP-{state['ticket_id']:05d}"
        handoff = agents.build_handoff(ticket_id=state["ticket_id"], rfp_id=rfp_id, metadata=metadata, plan=plan, findings=findings, summary=summary)
        sections = [{"department_id": w["department_id"], "reason": w["reason"], "key_aspects": w["key_aspects"], "asks": w["asks"], "figures": w["figures"],
                     "open_questions": w["open_questions"], "excerpts": w["excerpts"]} for w in handoff["workstreams"]]
        store.complete(state["ticket_id"], sections, handoff, summary.model_dump(), handoff["departments_needed"])
        return {"outcome": "completo"}

    builder = StateGraph(IntakeState)
    for name, fn in {NODE_CONVERT: convert, NODE_CLASSIFY: classify, NODE_DISCARD: discard, NODE_MEASURE: measure_node,
                     NODE_METADATA: extract_metadata, NODE_ORCHESTRATE: orchestrate, NODE_SYNTHESIZE: synthesize}.items():
        builder.add_node(name, tracked(name, fn))
    builder.add_node(NODE_WORKER, worker)
    builder.add_edge(START, NODE_CONVERT)
    builder.add_edge(NODE_CONVERT, NODE_CLASSIFY)
    builder.add_conditional_edges(NODE_CLASSIFY, route_after_classify, {NODE_DISCARD: NODE_DISCARD, NODE_MEASURE: NODE_MEASURE})
    builder.add_edge(NODE_DISCARD, END)
    builder.add_edge(NODE_MEASURE, NODE_METADATA)
    builder.add_edge(NODE_METADATA, NODE_ORCHESTRATE)
    builder.add_conditional_edges(NODE_ORCHESTRATE, fan_out, [NODE_WORKER])
    builder.add_edge(NODE_WORKER, NODE_SYNTHESIZE)
    builder.add_edge(NODE_SYNTHESIZE, END)
    return builder.compile()
