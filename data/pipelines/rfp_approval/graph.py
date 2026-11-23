"""Grafos de la Parte 3. Dos niveles, cada uno con su checkpoint (`thread_id` namespaced por ticket y por departamento):

  RAMA DE DEPARTAMENTO  (thread `rfp-{ticket}:{departamento}`; la pausa humana vive aquí)

      prepare ─▶ await_approval ──(interrupt)──▶ record ─┬─ aprobado ────────────▶ FIN
         ▲        ⏸ espera al humano                      ├─ cambios y quedan rondas ─▶ regenerate ─┐ (generador de la Parte 2,
         └──────────────────────────────────────────────────┘                                          solo ESTE departamento)
                                                          └─ rondas agotadas ─▶ escalate ─▶ FIN (árbitro: dueña del ticket)

  TICKET  (thread `rfp-{ticket}`; coordina, arbitra y cierra)

      open ─▶ converge ─┬─ ramas por lanzar ─Send×N─▶ branch[dept] (en paralelo, cada una hasta su interrupt) ─▶ FIN
                        ├─ todo aprobado + CEO ok + sin conflicto ─▶ synthesize ─▶ close (terminado)
                        └─ si no ─▶ FIN (el ticket sigue en esperando_aprobación)

Cada departamento tiene su propio hilo: pausar a uno NO bloquea a los demás (no hay barrera de superstep compartida). `resume` es un
punto de entrada explícito (`ApprovalEngine.resume`): reanuda SOLO el checkpoint de la rama que decidió. `converge` incluye el nodo de
arbitraje (`arbiter.detect`): determinista, con el árbitro fijo del BRIEFING §7."""
from __future__ import annotations

import logging
import operator
from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from data.pipelines import rfp_trace
from data.pipelines.rfp_intake.departments import DEPARTMENT_IDS
from data.pipelines.rfp_response import agents as part2_agents
from data.pipelines.rfp_response.agents import NotReady
from data.pipelines.rfp_response.graph import build_section_graph

from . import arbiter, config
from .document import build_final_document
from .packet import ceo_packet, department_packet
from .schemas import Decision
from .store import ApprovalStore

logger = logging.getLogger(__name__)


class BranchState(TypedDict, total=False):
    ticket_id: int
    department_id: str
    round: int
    packet: dict
    decision: dict
    outcome: str
    escalated: bool
    trace: Annotated[list[dict], operator.add]


class TicketState(TypedDict, total=False):
    ticket_id: int
    mode: str  # start | converge
    launch: list[str]
    ready: bool
    outcome: str
    trace: Annotated[list[dict], operator.add]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def regenerate_section(store: ApprovalStore, llm: Any, ticket_id: int, department_id: str, feedback: str) -> dict:
    """Devuelve la sección al GENERADOR de la Parte 2 (solo ese departamento) con el feedback humano o del árbitro, y la vuelve a
    evaluar con los tres evaluadores. No hay una nueva ejecución completa: es el mismo ciclo, con el mismo límite de iteraciones."""
    inp = store.get_part3_input(ticket_id)
    handoff, section = part2_agents.validate_handoff(inp["handoff"]), inp["sections"][department_id]
    state = {"ticket_id": ticket_id, "department_id": department_id, "max_iterations": config.part2.max_iterations(),
             "payload": part2_agents.generator_payload(handoff, department_id), "feedback": feedback, "evaluations": [],
             "draft": {"content": section.get("draft_content") or "", "pending_items": section.get("pending_items") or []}}
    result = build_section_graph(llm, store).invoke(state)["result"]
    store.approval_update(ticket_id, department_id, approval_status=config.APPROVAL_PENDING)
    return result


def build_department_graph(store: ApprovalStore, llm: Any, checkpointer: Any):
    def ev(state: dict, agent: str, node: str, inp: Any, out: Any) -> dict:
        return rfp_trace.emit(store, state["ticket_id"], part=3, agent=agent, node=node, input=inp, output=out,
                              thread_id=config.thread_id(state["ticket_id"], state["department_id"]))

    def prepare(state: BranchState) -> dict:
        t, d = state["ticket_id"], state["department_id"]
        inp = store.get_part3_input(t)
        section = inp["sections"][d]
        round_ = (section.get("approval_round") or 0) + 1
        packet = department_packet(t, d, round_, section, inp["handoff"], inp["ceo"], inp["conflicts_log"])
        store.heartbeat(t, f"await_approval:{d}")
        store.approval_update(t, d, approval_round=round_, approval_branch=config.BRANCH_WAITING)
        return {"round": round_, "packet": packet,
                "trace": [ev(state, f"human:{config.owner_of(d)}", "awaiting_approval", {"round": round_},
                             {"provisional": packet["provisional"], "conflicts": [c["trigger_id"] for c in packet["conflicts"]]})]}

    def await_approval(state: BranchState) -> dict:
        decision = interrupt(state["packet"])  # ⏸ el flujo se detiene aquí; el checkpoint conserva el estado hasta el resume
        return {"decision": Decision.model_validate(decision).model_dump()}

    def record(state: BranchState) -> dict:
        t, d, dec = state["ticket_id"], state["department_id"], Decision.model_validate(state["decision"])
        section = store.get_part3_input(t)["sections"][d]
        entry = {"round": state["round"], "action": dec.action, "approver": dec.approver, "comment": dec.comment, "at": _now(),
                 "submitted_by": dec.submitted_by, "figures": dec.figures, "escalated_decision": bool(section.get("escalated"))}
        fields = {"approval_comment": dec.comment or None, "approval_branch": config.BRANCH_IDLE,
                  "approval_history": (section.get("approval_history") or []) + [entry]}
        if dec.figures:
            fields["figures"] = {**(section.get("figures") or {}), **dec.figures}
        if dec.action == config.APPROVE:
            fields.update(approval_status=config.APPROVAL_APPROVED, approver=dec.approver, approved_at=entry["at"])
        else:
            fields.update(approval_status=config.APPROVAL_REJECTED if dec.action == config.REJECT else config.APPROVAL_PENDING,
                          approver=None, approved_at=None)
        store.approval_update(t, d, **fields)
        return {"outcome": dec.action, "trace": [ev(state, f"human:{dec.approver}", "decision", {"round": state["round"]},
                                                     {"action": dec.action, "comment": dec.comment})]}

    def after_record(state: BranchState) -> str:
        if state["outcome"] == config.APPROVE or state.get("escalated"):
            return END  # la decisión del árbitro es la última: no hay otra vuelta al generador
        return "escalate" if state["round"] >= config.max_rounds() else "regenerate"

    def regenerate(state: BranchState) -> dict:
        t, d = state["ticket_id"], state["department_id"]
        dec = Decision.model_validate(state["decision"])
        feedback = f"[REVISIÓN HUMANA · {dec.approver} · ronda {state['round']} · {dec.action}] {dec.comment}"
        store.heartbeat(t, f"regenerate:{d}")
        result = regenerate_section(store, llm, t, d, feedback)
        return {"trace": [ev(state, f"generator:{d}", "regenerate", {"feedback": feedback},
                             {"iterations": result["iterations"], "overall_pass": result["evaluation"]["overall_pass"]})]}

    def escalate(state: BranchState) -> dict:
        t, d = state["ticket_id"], state["department_id"]
        store.approval_update(t, d, escalated=True, approval_branch=config.BRANCH_IDLE)
        return {"outcome": "escalated", "escalated": True, "trace": [ev(state, f"arbiter:{config.ARBITER_NAME}", "escalated",
                                                     {"rounds": state["round"], "limit": config.max_rounds()},
                                                     {"escalated_to": config.ARBITER_NAME})]}

    g = StateGraph(BranchState)
    for name, fn in {"prepare": prepare, "await_approval": await_approval, "record": record, "regenerate": regenerate, "escalate": escalate}.items():
        g.add_node(name, fn)
    g.add_edge(START, "prepare")
    g.add_edge("prepare", "await_approval")
    g.add_edge("await_approval", "record")
    g.add_conditional_edges("record", after_record, {END: END, "escalate": "escalate", "regenerate": "regenerate"})
    g.add_edge("regenerate", "prepare")
    g.add_edge("escalate", "prepare")  # nueva pausa: ahora puede decidir también la dueña del ticket (árbitro fijo); será la última
    return g.compile(checkpointer=checkpointer)


def build_ceo_graph(store: ApprovalStore, checkpointer: Any):
    """Aprobación de la CEO (BRIEFING §5/§6/§7): una sola pausa, thread `rfp-{ticket}:ceo`. Su rechazo lo procesa `converge`."""
    def ev(state: dict, agent: str, node: str, inp: Any, out: Any) -> dict:
        return rfp_trace.emit(store, state["ticket_id"], part=3, agent=agent, node=node, input=inp, output=out,
                              thread_id=config.thread_id(state["ticket_id"], config.CEO_ID))

    def prepare(state: BranchState) -> dict:
        t = state["ticket_id"]
        inp = store.get_part3_input(t)
        ceo = inp["ceo"]
        round_ = (ceo.get("round") or 0) + 1
        packet = ceo_packet(t, round_, inp["sections"], inp["handoff"], ceo, inp["conflicts_log"])
        store.heartbeat(t, "await_approval:ceo")
        store.ticket_update(t, ceo_approval={**ceo, "round": round_, "branch": config.BRANCH_WAITING})
        return {"round": round_, "packet": packet, "trace": [ev(state, f"human:{config.CEO_NAME}", "awaiting_approval", {"round": round_},
                                                                {"estimated_annual_value_usd": ceo.get("estimated_annual_value_usd")})]}

    def await_approval(state: BranchState) -> dict:
        return {"decision": Decision.model_validate(interrupt(state["packet"])).model_dump()}

    def record(state: BranchState) -> dict:
        t, dec = state["ticket_id"], Decision.model_validate(state["decision"])
        ceo = store.get_part3_input(t)["ceo"]
        entry = {"round": state["round"], "action": dec.action, "approver": dec.approver, "comment": dec.comment, "at": _now(),
                 "submitted_by": dec.submitted_by}
        approved = dec.action == config.APPROVE
        store.ticket_update(t, ceo_approval={**ceo, "branch": config.BRANCH_IDLE, "history": (ceo.get("history") or []) + [entry], "handled": False,
                                             "status": config.APPROVAL_APPROVED if approved else config.APPROVAL_REJECTED,
                                             "approver": dec.approver if approved else None, "approved_at": entry["at"] if approved else None,
                                             "comment": dec.comment or None})
        return {"outcome": dec.action, "trace": [ev(state, f"human:{dec.approver}", "decision", {"round": state["round"]},
                                                     {"action": dec.action, "comment": dec.comment})]}

    g = StateGraph(BranchState)
    for name, fn in {"prepare": prepare, "await_approval": await_approval, "record": record}.items():
        g.add_node(name, fn)
    g.add_edge(START, "prepare")
    g.add_edge("prepare", "await_approval")
    g.add_edge("await_approval", "record")
    g.add_edge("record", END)
    return g.compile(checkpointer=checkpointer)


def build_ticket_graph(store: ApprovalStore, llm: Any, checkpointer: Any, department_graph: Any, ceo_graph: Any):
    def ev(state: dict, agent: str, node: str, inp: Any, out: Any) -> dict:
        return rfp_trace.emit(store, state["ticket_id"], part=3, agent=agent, node=node, input=inp, output=out,
                              thread_id=config.thread_id(state["ticket_id"]))

    def route_entry(state: TicketState) -> str:
        return "open" if state.get("mode", "start") == "start" else "converge"

    def open_(state: TicketState) -> dict:
        t = state["ticket_id"]
        inp = store.get_part3_input(t)
        if inp["status"] not in config.ENTRY_STATUSES:
            raise NotReady(f"El ticket está en «{inp['status']}»; la Parte 3 solo arranca desde {', '.join(config.ENTRY_STATUSES)}.")
        handoff = part2_agents.validate_handoff(inp["handoff"])
        if not (inp.get("part3_handoff") or {}).get("ready_for_part_3"):
            raise NotReady("La Parte 2 no dejó el handoff `ready_for_part_3`.")
        approvals = (handoff.get("approvals") or {}).get("ceo") or {}
        ceo = {"required": bool(approvals.get("required")), "estimated_annual_value_usd": approvals.get("estimated_annual_value_usd"),
               "status": config.APPROVAL_PENDING, "approver": None, "approved_at": None, "comment": None, "round": 0, "history": [],
               "branch": config.BRANCH_IDLE, "handled": False}
        store.heartbeat(t, "open")
        store.open_approval(t, ceo)
        provisional = [d for d, s in inp["sections"].items() if s.get("needs_human_review")]
        return {"trace": [ev(state, "approval-orchestrator", "open", {"status_before": inp["status"]},
                             {"status": config.STATUS_AWAITING, "departments": list(inp["sections"]), "provisional": provisional,
                              "ceo_required": ceo["required"]})]}

    def apply_forced(t: int, forced: dict[str, str], trigger: str, arbiter_name: str, events: list[dict], state: dict) -> None:
        sections = store.get_part3_input(t)["sections"]
        for dept, feedback in forced.items():
            sec = sections.get(dept)
            if sec is None or sec["approval_branch"] == config.BRANCH_WAITING or sec.get("escalated"):
                continue  # si la rama está esperando, el humano ya ve el conflicto en su ficha y decide; no se le pregunta dos veces
            if (sec.get("approval_round") or 0) >= config.max_rounds():  # límite de rondas: no más ciclos, se escala al árbitro
                store.approval_update(t, dept, escalated=True)
                events.append(ev(state, f"arbiter:{arbiter_name}", "escalated", {"trigger_id": trigger, "department_id": dept}, {"rounds": sec["approval_round"]}))
                continue
            result = regenerate_section(store, llm, t, dept, feedback)
            history = (sec.get("approval_history") or []) + [{"round": sec["approval_round"], "action": "forced_changes", "approver": arbiter_name,
                                                              "trigger_id": trigger, "comment": feedback, "at": _now()}]
            store.approval_update(t, dept, approval_status=config.APPROVAL_PENDING, approver=None, approved_at=None, approval_comment=feedback,
                                  approval_branch=config.BRANCH_IDLE, approval_history=history)
            events.append(ev(state, f"arbiter:{arbiter_name}", "forced_changes", {"trigger_id": trigger, "department_id": dept, "feedback": feedback},
                             {"generator_iterations": result["iterations"], "regenerated": True}))

    def converge(state: TicketState) -> dict:
        t, events = state["ticket_id"], []
        inp = store.get_part3_input(t)
        if inp["status"] != config.STATUS_AWAITING:
            raise NotReady(f"El ticket está en «{inp['status']}», no en {config.STATUS_AWAITING}.")
        store.heartbeat(t, "converge")
        ceo = inp["ceo"]
        # 1) Rechazo de la CEO (ruta de rechazo, BRIEFING §7): la sección dueña (marketing) vuelve a cambios con su comentario.
        if ceo.get("status") == config.APPROVAL_REJECTED and not ceo.get("handled"):
            comment = (ceo.get("history") or [{}])[-1].get("comment", "")
            ceo = {**ceo, "status": config.APPROVAL_PENDING, "handled": True}
            store.ticket_update(t, ceo_approval=ceo)
            apply_forced(t, {config.OWNER_DEPARTMENT: f"[CEO · {config.CEO_NAME} rechaza · {arbiter.BRIEFING_REF}] {comment} "
                                                       "Sube el precio o reduce el alcance."}, config.TRIGGER_CEO, config.CEO_NAME, events, state)
        # 2) Arbitraje: triggers del BRIEFING sobre el estado estructurado, con árbitro fijo (sin LLM).
        inp = store.get_part3_input(t)
        sections, ceo = inp["sections"], inp["ceo"]
        overridden = set()
        if any((s.get("approval_status") == config.APPROVAL_APPROVED and (s.get("approval_history") or [{}])[-1].get("escalated_decision"))
               for d, s in sections.items() if d in ("operaciones", "procurement")):
            overridden.add(f"{config.TRIGGER_COST}:operaciones,procurement")  # el árbitro (Camila) resolvió tras agotar rondas
        detected = arbiter.detect(sections, ceo, overridden)
        log, new = arbiter.merge_log(inp["conflicts_log"], detected)
        store.ticket_update(t, conflicts_log=log)
        for c in new:
            events.append(ev(state, f"arbiter:{c['arbiter']}", "conflict_detected", {"trigger_id": c["trigger_id"], "departments": c["departments"]},
                             {"resolution": c["resolution"], "evidence": c["evidence"], "blocking": c["blocking"]}))
        for c in detected:
            if c["forced_changes"]:
                apply_forced(t, c["forced_changes"], c["trigger_id"], c["arbiter"], events, state)
        # 3) ¿qué ramas hay que abrir y está todo listo para sintetizar?
        inp = store.get_part3_input(t)
        sections, ceo = inp["sections"], inp["ceo"]
        detected = arbiter.detect(sections, ceo, overridden)
        log, _ = arbiter.merge_log(inp["conflicts_log"], detected)  # tras los cambios forzados, cierra los conflictos que ya no existen
        store.ticket_update(t, conflicts_log=log)
        def arbiter_decided(sec: dict) -> bool:  # una sección escalada se pausa una sola vez para el árbitro
            last = (sec.get("approval_history") or [{}])[-1]
            return bool(sec.get("escalated") and last.get("escalated_decision"))

        launch = [d for d, s in sections.items()
                  if s["approval_status"] != config.APPROVAL_APPROVED and s["approval_branch"] != config.BRANCH_WAITING and not arbiter_decided(s)]
        all_approved = all(s["approval_status"] == config.APPROVAL_APPROVED for s in sections.values())
        if all_approved and ceo.get("required") and ceo.get("status") != config.APPROVAL_APPROVED and ceo.get("branch") != config.BRANCH_WAITING:
            launch.append(config.CEO_ID)  # la CEO decide sobre la propuesta ya aprobada por todos los departamentos
        blocking = [c for c in detected if c["blocking"] and c["trigger_id"] != config.TRIGGER_CEO]
        ceo_ok = not ceo.get("required") or ceo.get("status") == config.APPROVAL_APPROVED
        ready = all_approved and ceo_ok and not blocking
        events.append(ev(state, "approval-orchestrator", "converge", {"mode": state.get("mode")},
                         {"launch": launch, "ready": ready, "approved": [d for d, s in sections.items() if s["approval_status"] == config.APPROVAL_APPROVED],
                          "open_conflicts": [c["trigger_id"] for c in detected], "escalated": [d for d, s in sections.items() if s.get("escalated")]}))
        return {"launch": launch, "ready": ready, "trace": events}

    def after_converge(state: TicketState):
        if state["ready"]:
            return "synthesize"
        if state["launch"]:
            return [Send("branch", {"ticket_id": state["ticket_id"], "department_id": d}) for d in state["launch"]]
        return END

    def branch(payload: dict) -> dict:
        """Una rama de departamento (o de la CEO) corre en su propio hilo hasta su interrupt. Si una revienta, las demás siguen."""
        t, d = payload["ticket_id"], payload["department_id"]
        graph = ceo_graph if d == config.CEO_ID else department_graph
        try:
            graph.invoke({"ticket_id": t, "department_id": d}, {"configurable": {"thread_id": config.thread_id(t, d)}})
            return {}
        except Exception as exc:  # noqa: BLE001
            logger.exception("rfp_approval: falló la rama %s del ticket %s", d, t)
            store.ticket_update(t, processing_error=f"Rama {d}: {type(exc).__name__}: {str(exc)[:300]}")
            return {"trace": [ev(payload, f"approval-branch:{d}", "branch_failed", {}, {"error": str(exc)[:300]})]}

    def synthesize(state: TicketState) -> dict:
        t = state["ticket_id"]
        if not store.claim_close(t):  # dos aprobaciones simultáneas no generan el documento dos veces
            return {"outcome": "ya_en_cierre"}
        inp = store.get_part3_input(t)
        document = build_final_document(t, part2_agents.validate_handoff(inp["handoff"]), inp["sections"], inp["ceo"])
        store.save_final_document(t, document)
        return {"outcome": "documento", "trace": [ev(state, "ultimate-synthesizer", "synthesize", {"sections": [s["department_id"] for s in document["sections"]]},
                                                      {"characters": len(document["content"]), "total_estimated_value": document["total_estimated_value"],
                                                       "compliance": document["compliance"]["pass"]})]}

    def close(state: TicketState) -> dict:
        if state.get("outcome") != "documento":
            return {}
        store.complete_approval(state["ticket_id"])
        return {"outcome": "terminado", "trace": [ev(state, "approval-orchestrator", "close", {}, {"status": config.STATUS_DONE})]}

    g = StateGraph(TicketState)
    for name, fn in {"open": open_, "converge": converge, "branch": branch, "synthesize": synthesize, "close": close}.items():
        g.add_node(name, fn)
    g.add_conditional_edges(START, route_entry, {"open": "open", "converge": "converge"})
    g.add_edge("open", "converge")
    g.add_conditional_edges("converge", after_converge, ["synthesize", "branch", END])
    g.add_edge("branch", END)
    g.add_edge("synthesize", "close")
    g.add_edge("close", END)
    return g.compile(checkpointer=checkpointer)


__all__ = ["DEPARTMENT_IDS", "build_ceo_graph", "build_department_graph", "build_ticket_graph", "regenerate_section"]
