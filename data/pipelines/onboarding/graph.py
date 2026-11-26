"""Grafo del orquestador de onboarding: UN solo agente con estado, un thread por incorporación (`onboarding-{id}`).

    START ─▶ enter_stage ─┬─ etapa de contenido ─▶ quiz_prepare ─▶ await_quiz ⏸ ─┬─ superada ─┬─ con aprobación (etapa 5) ─▶ await_approval ⏸
              ▲           │                           ▲                          │            └─ sin aprobación ──────────▶ advance
              │           │                           └──── reinforce ◀── no superada (≥2 intentos: avisa al responsable)
              │           └─ trámites / jornada / cierre ─▶ await_approval ⏸ ─┬─ aprueba ─▶ advance ─▶ (etapa siguiente | finish)
              └──────────────────────────────── rechaza: vuelve al INICIO de la misma etapa, con el comentario visible ┘

⏸ = `interrupt` de LangGraph: el agente se detiene de verdad (el estado queda en el checkpoint) y NO avanza hasta recibir la respuesta
(`Command(resume=…)`): las respuestas de la comprobación o la decisión de una persona con el permiso adecuado. Los nodos no tocan nada
fuera de lo que el BRIEFING permite; cada acción queda en `events` como acción del proceso automatizado, no de una persona."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from . import config, knowledge, quiz, schedule
from .sensitive import redact
from .store import OnboardingStore

ACTOR_AUTOMATED, ACTOR_PERSON = "automated_process", "person"


class PermissionDenied(PermissionError):
    pass


class AgentIdentity:
    """Identidad PROPIA del agente (no usa la cuenta de nadie) y con permisos más acotados que los de cualquier persona del equipo.
    Toda acción del agente pasa por `act`, que exige el permiso y deja el evento firmado como proceso automatizado."""
    actor_type = ACTOR_AUTOMATED
    actor_id = config.AGENT_ACTOR

    def __init__(self, store: OnboardingStore, clock: Callable[[], datetime]):
        self.store, self.clock = store, clock

    def require(self, permission: str) -> None:
        if permission not in config.AGENT_PERMISSIONS:
            raise PermissionDenied(f"El agente de onboarding no tiene el permiso «{permission}»")

    def act(self, permission: str, onboarding_id: str | None, action: str, detail: dict | None = None) -> None:
        self.require(permission)
        self.store.log_event(onboarding_id, self.actor_type, self.actor_id, action, detail or {}, self.clock())

    def notify(self, onboarding_id: str | None, recipient_kind: str, recipient_id: str, kind: str, stage: int | None, message: str) -> None:
        self.require("notify")
        self.store.notify(recipient_kind, recipient_id, onboarding_id, kind, stage, message, self.clock())
        self.act("notify", onboarding_id, f"notify:{kind}", {"to": f"{recipient_kind}:{recipient_id}", "stage": stage})


class State(TypedDict, total=False):
    onboarding_id: str
    stage: int
    outcome: str


def build_graph(store: OnboardingStore, agent: AgentIdentity, checkpointer: Any, kb_dir: str | None = None):
    def rec(state: State) -> dict:
        return store.onboarding(state["onboarding_id"])

    def enter_stage(state: State) -> dict:
        record, stage = rec(state), config.STAGE_BY_NUMBER[state["stage"]]
        from datetime import date

        deadline = schedule.deadline_at(date.fromisoformat(record["start_date"]), stage.deadline_day, record["site"])
        store.activate_stage(record["id"], stage.number, agent.clock(), deadline)
        agent.act("record_stage_status", record["id"], "stage_entered", {"stage": stage.number, "title": stage.title})
        return {"outcome": ""}

    def after_enter(state: State) -> str:
        return "quiz_prepare" if config.STAGE_BY_NUMBER[state["stage"]].quiz else "await_approval"

    def quiz_prepare(state: State) -> dict:
        record, stage = rec(state), config.STAGE_BY_NUMBER[state["stage"]]
        attempts = store.stage(record["id"], stage.number)["attempts"]
        questions = quiz.select(stage, record["variant"], record["id"], attempts, kb_dir)
        previous = store.quiz(record["id"]) or {}
        store.set_quiz(record["id"], stage.number, attempts, [q.id for q in questions], previous.get("failed_sources", []), previous.get("last_score"))
        agent.act("present_content", record["id"], "content_presented", {"stage": stage.number, "attempt": attempts + 1, "questions": len(questions)})
        return {}

    def await_quiz(state: State) -> dict:
        record, stage = rec(state), config.STAGE_BY_NUMBER[state["stage"]]
        current = store.quiz(record["id"])
        # ⏸ El agente se detiene aquí hasta que la persona envíe sus respuestas.
        answers = interrupt({"kind": "quiz", "stage": stage.number, "attempt": current["attempt"], "question_ids": current["question_ids"]})
        questions = [quiz.question_by_id(stage, record["variant"], qid, kb_dir) for qid in current["question_ids"]]
        grade = quiz.grade(questions, {k: int(v) for k, v in answers.items()})
        store.update_stage(record["id"], stage.number, attempts=current["attempt"] + 1)
        store.set_quiz(record["id"], stage.number, current["attempt"], current["question_ids"],
                       [] if grade.passed else list(grade.failed_sources), grade.score)
        agent.act("grade_comprehension", record["id"], "quiz_graded",
                  {"stage": stage.number, "attempt": current["attempt"] + 1, "correct": grade.correct, "total": grade.total, "passed": grade.passed})
        return {"outcome": "pass" if grade.passed else "fail"}

    def after_quiz(state: State) -> str:
        if state["outcome"] == "fail":
            return "reinforce"
        return "await_approval" if config.STAGE_BY_NUMBER[state["stage"]].approver else "advance"

    def reinforce(state: State) -> dict:
        record, stage = rec(state), config.STAGE_BY_NUMBER[state["stage"]]
        progress = store.stage(record["id"], stage.number)
        agent.act("present_content", record["id"], "content_reinforced", {"stage": stage.number, "attempt": progress["attempts"]})
        if progress["attempts"] >= config.FAILED_ATTEMPTS_BEFORE_NOTIFY and not progress["quiz_failure_notified_at"]:
            agent.notify(record["id"], "staff", record["manager_id"], "quiz_failed_twice", stage.number,
                         f"{record['name']} no ha superado dos veces la comprobación de la etapa «{stage.title}». Conviene acompañarle.")
            store.update_stage(record["id"], stage.number, quiz_failure_notified_at=agent.clock().isoformat())
        return {}

    def await_approval(state: State) -> dict:
        record, stage = rec(state), config.STAGE_BY_NUMBER[state["stage"]]
        # ⏸ El agente se detiene aquí: no hay ninguna rama que lo salte; solo avanza con la decisión de una persona autorizada.
        decision = interrupt({"kind": "approval", "stage": stage.number, "approver": stage.approver, "approver_label": stage.approver_label})
        verdict = decision["decision"]
        comment, _ = redact(decision.get("comment") or "")
        store.log_event(record["id"], ACTOR_PERSON, decision["actor_id"], f"stage_{verdict}d" if verdict == "approve" else "stage_rejected",
                        {"stage": stage.number, "comment": comment, "flags": decision.get("flags", {})}, agent.clock())
        if verdict == "approve":
            flags = decision.get("flags") or {}
            if stage.number == 1:
                store.set_paperwork(record["id"], contract_received=bool(flags.get("contract_received")), payroll_docs_received=bool(flags.get("payroll_docs_received")))
            elif stage.number == 4:
                store.set_paperwork(record["id"], shadow_day_confirmed=True)
            elif stage.number == 8:
                store.set_paperwork(record["id"], accesses_confirmed=bool(flags.get("accesses_confirmed")))
            return {"outcome": "approved"}
        store.update_stage(record["id"], stage.number, rejections=store.stage(record["id"], stage.number)["rejections"] + 1, last_comment=comment)
        agent.notify(record["id"], "person", record["id"], "stage_rejected", stage.number,
                     f"La etapa «{stage.title}» volvió a su inicio. Comentario de {stage.approver_label}: {comment}")
        return {"outcome": "rejected"}

    def after_approval(state: State) -> str:
        return "advance" if state["outcome"] == "approved" else "enter_stage"  # rechazo: vuelve al inicio de ESA etapa

    def advance(state: State) -> dict:
        record, stage = rec(state), config.STAGE_BY_NUMBER[state["stage"]]
        store.update_stage(record["id"], stage.number, status="completed", completed_at=agent.clock().isoformat())
        agent.act("record_stage_status", record["id"], "stage_completed", {"stage": stage.number, "title": stage.title})
        return {"stage": stage.number + 1} if stage.number < config.LAST_STAGE else {"outcome": "done"}

    def after_advance(state: State) -> str:
        return "finish" if state.get("outcome") == "done" else "enter_stage"

    def finish(state: State) -> dict:
        record = rec(state)
        store.update_onboarding(record["id"], status="completed", completed_at=agent.clock().isoformat())
        agent.act("record_stage_status", record["id"], "onboarding_completed", {})
        agent.notify(record["id"], "person", record["id"], "onboarding_completed", config.LAST_STAGE, "Has completado tu onboarding corporativo. ¡Bienvenido a Brasaland!")
        return {}

    builder = StateGraph(State)
    for name, node in [("enter_stage", enter_stage), ("quiz_prepare", quiz_prepare), ("await_quiz", await_quiz), ("reinforce", reinforce),
                       ("await_approval", await_approval), ("advance", advance), ("finish", finish)]:
        builder.add_node(name, node)
    builder.add_edge(START, "enter_stage")
    builder.add_conditional_edges("enter_stage", after_enter, ["quiz_prepare", "await_approval"])
    builder.add_edge("quiz_prepare", "await_quiz")
    builder.add_conditional_edges("await_quiz", after_quiz, ["reinforce", "await_approval", "advance"])
    builder.add_edge("reinforce", "quiz_prepare")
    builder.add_conditional_edges("await_approval", after_approval, ["advance", "enter_stage"])
    builder.add_conditional_edges("advance", after_advance, ["finish", "enter_stage"])
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=checkpointer)
