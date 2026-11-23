"""Grafo LangGraph DEDICADO `rfp_response` (Parte 2). No se mezcla con `rfp_intake` (Parte 1) ni con el grafo CX.

  load ──Send×N──▶ section[dept] ──▶ finish          (los departamentos corren EN PARALELO y no se esperan entre sí)
                     │
                     └─ subgrafo por departamento (ciclo generador-evaluador con límite):

        generate ─▶ to_eval ──Send×3──▶ eval_readability ┐
            ▲                           eval_relevance   ├─▶ decide ─┬─ pasa ─────────────▶ finalize (paso)
            │                           eval_compliance  ┘           ├─ falla y quedan intentos ─▶ generate (con feedback)
            └────────────────────────────────────────────────────────┘└─ falla y se agotaron ───▶ finalize (needs_human_review)

Estado compartido sin carreras: los 3 evaluadores NO escriben el mismo campo; cada uno añade su resultado a una lista con
reducer `operator.add` (clave: tipo + iteración) y solo `decide`, que corre cuando los tres terminaron, los fusiona.
Cada evaluador recibe únicamente lo que necesita (no el estado completo ni el documento).
"""
from __future__ import annotations

import logging
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from data.pipelines import rfp_trace
from data.pipelines.rfp_intake.departments import DEPARTMENT_IDS

from . import agents, config
from .agents import Llm, NotReady
from .rules import evaluate_compliance, evaluate_readability
from .store import ResponseStore

logger = logging.getLogger(__name__)
KINDS = ("readability", "relevance", "compliance")


class SectionState(TypedDict, total=False):
    ticket_id: int
    department_id: str
    payload: dict
    max_iterations: int
    iteration: int
    draft: dict
    feedback: str
    evaluations: Annotated[list[dict], operator.add]
    history: list[dict]
    verdict: str
    result: dict


class ResponseState(TypedDict, total=False):
    ticket_id: int
    mode: str  # start | resume | regenerate
    handoff: dict
    to_generate: list[str]
    sections: Annotated[list[dict], operator.add]
    errors: Annotated[list[dict], operator.add]
    outcome: str


def build_section_graph(llm: Llm, store: ResponseStore):
    def generate(state: SectionState) -> dict:
        t, dept, it = state["ticket_id"], state["department_id"], state.get("iteration", 0) + 1
        store.heartbeat(t, f"generate:{dept}#{it}")
        store.section_update(t, dept, generation_status=config.SECTION_GENERATING, iterations=it)
        draft = agents.generate_section(llm, dept, state["payload"], state.get("draft"), state.get("feedback", "")).model_dump()
        store.section_update(t, dept, draft_content=draft["content"], pending_items=draft["pending_items"])
        rfp_trace.emit(store, t, part=2, agent=f"generator:{dept}", node="generate", input={"iteration": it, "feedback": state.get("feedback", "")},
                       output={"characters": len(draft["content"]), "pending_items": draft["pending_items"]})
        return {"iteration": it, "draft": draft}

    def to_eval(state: SectionState) -> dict:
        store.mark_evaluating(state["ticket_id"])
        store.section_update(state["ticket_id"], state["department_id"], generation_status=config.SECTION_EVALUATING)
        return {}

    def fan_out(state: SectionState) -> list[Send]:
        base = {"ticket_id": state["ticket_id"], "department_id": state["department_id"], "iteration": state["iteration"],
                "text": state["draft"]["content"]}
        return [Send("eval_readability", base),
                Send("eval_relevance", {**base, "key_aspects": state["payload"]["workstream"]["key_aspects"]}),
                Send("eval_compliance", {**base, "allowed_numbers": sorted(agents.allowed_numbers(state["payload"]))})]

    def eval_readability(p: dict) -> dict:
        store.heartbeat(p["ticket_id"], f"eval-readability:{p['department_id']}")
        result = evaluate_readability(p["text"])
        rfp_trace.emit(store, p["ticket_id"], part=2, agent=f"evaluator-readability:{p['department_id']}", node="eval_readability",
                       input={"iteration": p["iteration"]}, output={"pass": result["pass"], "score": result["score"]})
        return {"evaluations": [{"kind": "readability", "iteration": p["iteration"], "result": result}]}

    def eval_relevance(p: dict) -> dict:
        store.heartbeat(p["ticket_id"], f"eval-relevance:{p['department_id']}")
        result = agents.evaluate_relevance(llm, p["key_aspects"], p["text"])
        rfp_trace.emit(store, p["ticket_id"], part=2, agent=f"evaluator-relevance:{p['department_id']}", node="eval_relevance",
                       input={"iteration": p["iteration"], "aspects": len(p["key_aspects"])},
                       output={"pass": result["pass"], "missing_aspects": result["missing_aspects"]})
        return {"evaluations": [{"kind": "relevance", "iteration": p["iteration"], "result": result}]}

    def eval_compliance(p: dict) -> dict:
        store.heartbeat(p["ticket_id"], f"eval-compliance:{p['department_id']}")
        result = evaluate_compliance(p["text"], p["department_id"], set(p["allowed_numbers"]))
        rfp_trace.emit(store, p["ticket_id"], part=2, agent=f"evaluator-compliance:{p['department_id']}", node="eval_compliance",
                       input={"iteration": p["iteration"]}, output={"pass": result["pass"], "rule_ids": result["rule_ids"]})
        return {"evaluations": [{"kind": "compliance", "iteration": p["iteration"], "result": result}]}

    def decide(state: SectionState) -> dict:
        it = state["iteration"]
        current = {e["kind"]: e["result"] for e in state["evaluations"] if e["iteration"] == it}
        if set(current) != set(KINDS):
            raise RuntimeError(f"Faltan evaluaciones de la iteración {it}: {sorted(set(KINDS) - set(current))}")
        evaluation = agents.build_evaluation(state["ticket_id"], state["department_id"], it, current["readability"],
                                             current["relevance"], current["compliance"],
                                             state["payload"]["workstream"]["key_aspects"])
        history = list(state.get("history", [])) + [{"iteration": it, "draft_content": state["draft"]["content"], "evaluation": evaluation}]
        store.section_update(state["ticket_id"], state["department_id"], evaluation_results=evaluation, evaluation_history=history)
        verdict = "pass" if evaluation["overall_pass"] else ("retry" if it < state["max_iterations"] else "exhausted")
        rfp_trace.emit(store, state["ticket_id"], part=2, agent=f"evaluator-decision:{state['department_id']}", node="decide",
                       input={"iteration": it, "max_iterations": state["max_iterations"]}, output={"verdict": verdict, "rule_ids": evaluation["compliance"]["rule_ids"]})
        return {"history": history, "verdict": verdict, "feedback": evaluation["feedback_for_generator"]}

    def finalize(state: SectionState) -> dict:
        passed = state["verdict"] == "pass"
        status = config.SECTION_PASSED if passed else config.SECTION_NEEDS_REVIEW
        evaluation = state["history"][-1]["evaluation"]
        store.section_update(state["ticket_id"], state["department_id"], generation_status=status, needs_human_review=not passed,
                             evaluation_results=evaluation, iterations=state["iteration"])
        return {"result": {"department_id": state["department_id"], "draft": state["draft"], "evaluation": evaluation,
                           "history": state["history"], "iterations": state["iteration"], "needs_human_review": not passed}}

    g = StateGraph(SectionState)
    for name, fn in {"generate": generate, "to_eval": to_eval, "eval_readability": eval_readability, "eval_relevance": eval_relevance,
                     "eval_compliance": eval_compliance, "decide": decide, "finalize": finalize}.items():
        g.add_node(name, fn)
    g.add_edge(START, "generate")
    g.add_edge("generate", "to_eval")
    g.add_conditional_edges("to_eval", fan_out, ["eval_readability", "eval_relevance", "eval_compliance"])
    g.add_edge(["eval_readability", "eval_relevance", "eval_compliance"], "decide")  # unión: espera a los tres
    g.add_conditional_edges("decide", lambda s: "generate" if s["verdict"] == "retry" else "finalize", {"generate": "generate", "finalize": "finalize"})
    g.add_edge("finalize", END)
    return g.compile()


ALLOWED_FROM = {"start": ("analisis_completo",),
                "resume": (config.STATUS_GENERATING, config.STATUS_EVALUATING),
                "regenerate": ("analisis_completo", config.STATUS_GENERATING, config.STATUS_EVALUATING, config.STATUS_NEEDS_REVIEW)}


def build_graph(llm: Llm, store: ResponseStore):
    section_graph = build_section_graph(llm, store)

    def load(state: ResponseState) -> dict:
        t, mode = state["ticket_id"], state.get("mode", "start")
        inp = store.get_part2_input(t)
        if inp["status"] not in ALLOWED_FROM[mode]:
            raise NotReady(f"El ticket está en «{inp['status']}»; la Parte 2 ({mode}) solo arranca desde {', '.join(ALLOWED_FROM[mode])}.")
        handoff = agents.validate_handoff(inp["handoff"])
        departments = [d for d in DEPARTMENT_IDS if any(w["department_id"] == d for w in handoff["workstreams"])]
        resume = mode == "resume"
        kept = [s for s in (inp["sections"].get(d) for d in departments) if resume and s and s.get("generation_status") in config.SECTION_FINAL]
        to_generate = [d for d in departments if d not in {k["department_id"] for k in kept}]
        store.begin_generation(t, to_generate, resume)
        store.heartbeat(t, "load")
        rfp_trace.emit(store, t, part=2, agent="response-orchestrator", node="load", input={"mode": mode, "status": inp["status"]},
                       output={"departments": departments, "to_generate": to_generate})
        carried = [{"department_id": k["department_id"], "draft": {"content": k.get("draft_content") or "", "pending_items": k.get("pending_items") or []},
                    "evaluation": k["evaluation_results"], "history": k.get("evaluation_history") or [], "iterations": k.get("iterations") or 0,
                    "needs_human_review": bool(k.get("needs_human_review"))} for k in kept]
        return {"handoff": handoff, "to_generate": to_generate, "sections": carried}

    def fan_out(state: ResponseState) -> list[Send]:
        limit = config.max_iterations()
        return [Send("section", {"ticket_id": state["ticket_id"], "department_id": d, "max_iterations": limit,
                                 "payload": agents.generator_payload(state["handoff"], d)}) for d in state["to_generate"]]

    def section(payload: dict) -> dict:
        """Un departamento: si su ciclo revienta, se registra y los demás siguen (no se bloquean entre sí)."""
        try:
            return {"sections": [section_graph.invoke({**payload, "evaluations": []})["result"]]}
        except Exception as exc:  # noqa: BLE001
            logger.exception("rfp_response: falló la sección %s del ticket %s", payload["department_id"], payload["ticket_id"])
            message = f"{type(exc).__name__}: {str(exc)[:300]}"
            store.section_update(payload["ticket_id"], payload["department_id"], generation_status=config.SECTION_ERROR, generation_error=message)
            return {"errors": [{"department_id": payload["department_id"], "error": message}]}

    def finish(state: ResponseState) -> dict:
        t = state["ticket_id"]
        if state.get("errors"):
            raise RuntimeError("Fallaron las secciones: " + "; ".join(f"{e['department_id']} ({e['error']})" for e in state["errors"]))
        sections = sorted(state["sections"], key=lambda s: DEPARTMENT_IDS.index(s["department_id"]))
        review = any(s["needs_human_review"] for s in sections)
        status = config.STATUS_NEEDS_REVIEW if review else config.STATUS_EVALUATING
        store.heartbeat(t, "finish")
        rfp_trace.emit(store, t, part=2, agent="response-orchestrator", node="finish", input={"sections": [s["department_id"] for s in sections]},
                       output={"status": status, "needs_human_review": [s["department_id"] for s in sections if s["needs_human_review"]]})
        store.complete_generation(t, status, agents.build_part3_handoff(t, state["handoff"], sections, status))
        return {"outcome": "revision_humana" if review else "completo"}

    g = StateGraph(ResponseState)
    g.add_node("load", load)
    g.add_node("section", section)
    g.add_node("finish", finish)
    g.add_edge(START, "load")
    g.add_conditional_edges("load", fan_out, ["section"])
    g.add_edge("section", "finish")
    g.add_edge("finish", END)
    return g.compile()
