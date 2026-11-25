"""Punto de entrada del orquestador: alta de incorporaciones, respuestas de la persona, decisiones de los aprobadores, dudas, vistas y
seguimiento (recordatorios y escalados). Toda entrada humana se VALIDA aquí antes de tocar el checkpoint (rol, departamento, estado
del flujo); el grafo solo recibe decisiones ya autorizadas. Ninguna excepción del trabajo en segundo plano escapa al proceso: se anota en
la incorporación (`processing_error`) y se puede reintentar."""
from __future__ import annotations

import logging
import threading
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Callable

from langgraph.types import Command

from . import config, knowledge, quiz, schedule
from .checkpoint import build_checkpointer
from .graph import ACTOR_PERSON, AgentIdentity, build_graph
from .sensitive import redact
from .store import OnboardingStore, parse

logger = logging.getLogger(__name__)


class OnboardingError(Exception):
    status_code = 422

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotCorporate(OnboardingError):
    pass


class Forbidden(OnboardingError):
    status_code = 403


class NotAwaiting(OnboardingError):
    status_code = 409


def thread_id(onboarding_id: str) -> str:
    return f"onboarding-{onboarding_id}"


def approver_allowed(stage: config.Stage, staff: dict | None, record: dict) -> bool:
    """¿Esta persona tiene el rol y el departamento adecuados para aprobar ESTA etapa? (BRIEFING: «Nadie más».)"""
    if staff is None or stage.approver is None:
        return False
    if stage.approver == "people_team":
        return staff["department"] == "Personas" and staff["role"] in (config.ROLE_PEOPLE_TEAM, config.ROLE_PEOPLE_MANAGER)
    if stage.approver == "ops_supervisor":
        return staff["department"] == "Operaciones" and staff["role"] == config.ROLE_OPS_SUPERVISOR
    if stage.approver == "direct_manager":
        return staff["id"] == record["manager_id"]
    if stage.approver == "people_manager":
        return staff["role"] == config.ROLE_PEOPLE_MANAGER
    return False


class OnboardingEngine:
    def __init__(self, store: OnboardingStore | None = None, checkpointer: Any = None, clock: Callable[[], datetime] | None = None,
                 kb_dir: str | None = None):
        self.store = store or OnboardingStore()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.kb_dir = kb_dir
        self.agent = AgentIdentity(self.store, self.clock)
        self.checkpointer = checkpointer if checkpointer is not None else build_checkpointer()
        self.graph = build_graph(self.store, self.agent, self.checkpointer, kb_dir)
        self._locks: dict[str, threading.RLock] = defaultdict(threading.RLock)  # un avance a la vez POR incorporación; entre ellas, en paralelo

    @staticmethod
    def _cfg(onboarding_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id(onboarding_id)}}

    # ---- alta ---------------------------------------------------------------------------------------------------------------
    def register(self, actor_id: str, data: dict) -> dict:
        """Valida y crea la incorporación (todavía sin arrancar el agente). Rechaza los puestos de restaurante con el mensaje del BRIEFING."""
        department, position, site = data["department"], data["position"], data["site"]
        if not config.is_corporate(department, position):
            raise NotCorporate(config.NOT_CORPORATE_MESSAGE)
        if site not in config.SITES:
            raise OnboardingError("La sede debe ser Medellín o Miami.")
        variant = config.variant_for(department, position)
        if variant is None:
            raise OnboardingError("No existe material oficial de «Tu función» para ese puesto. Pide a Personas que lo prepare antes de iniciar el onboarding.")
        manager = self.store.staff(data["manager_id"])
        if manager is None or manager["role"] != config.ROLE_MANAGER:
            raise OnboardingError("El responsable directo no existe o no figura como responsable en el directorio.")
        if self.store.onboarding_by_email(data["email"]):
            raise OnboardingError("Ya existe un onboarding para esa persona.")
        record = {"id": f"ob-{uuid.uuid4().hex[:8]}", "name": data["name"], "email": data["email"], "position": position, "department": department,
                  "site": site, "manager_id": manager["id"], "variant": variant, "start_date": str(data["start_date"])}
        self.store.create_onboarding(record, self.clock())
        self.store.log_event(record["id"], ACTOR_PERSON, actor_id, "onboarding_registered",
                             {"position": position, "department": department, "site": site, "start_date": record["start_date"]}, self.clock())
        return self.store.onboarding(record["id"])

    def start(self, onboarding_id: str) -> None:
        """Arranca el agente hasta su primera pausa. Pensado para ejecutarse en segundo plano; no lanza."""
        self._run(onboarding_id, {"onboarding_id": onboarding_id, "stage": 1})

    def _run(self, onboarding_id: str, payload: Any) -> None:
        with self._locks[onboarding_id]:
            try:
                self.graph.invoke(payload, self._cfg(onboarding_id))
                self.store.update_onboarding(onboarding_id, processing_error=None)
            except Exception as error:  # noqa: BLE001 - se registra y se puede reintentar; nunca tumba el proceso
                logger.exception("Fallo del orquestador en %s", onboarding_id)
                self.store.update_onboarding(onboarding_id, processing_error=f"{type(error).__name__}: {error}"[:300])

    # ---- estado del hilo ----------------------------------------------------------------------------------------------------
    def awaiting(self, onboarding_id: str) -> dict | None:
        """Qué espera el agente ahora (la carga del `interrupt` pendiente), leído del CHECKPOINT: es la verdad tras un reinicio."""
        snapshot = self.graph.get_state(self._cfg(onboarding_id))
        for task in snapshot.tasks:
            if task.interrupts:
                return dict(task.interrupts[0].value)
        return None

    # ---- la persona incorporada: comprobación -------------------------------------------------------------------------------
    def check_answers(self, onboarding_id: str, answers: dict) -> dict:
        pending = self.awaiting(onboarding_id)
        if not pending or pending["kind"] != "quiz":
            raise NotAwaiting("Ahora mismo no hay ninguna comprobación pendiente.")
        expected = set(pending["question_ids"])
        if set(answers) != expected:
            raise OnboardingError("Debes responder exactamente a las preguntas de la comprobación actual.")
        for qid, choice in answers.items():
            if not isinstance(choice, int) or isinstance(choice, bool) or not 0 <= choice <= 3:
                raise OnboardingError(f"Respuesta no válida en {qid}.")
        return pending

    def apply_answers(self, onboarding_id: str, answers: dict) -> None:
        pending = self.awaiting(onboarding_id)  # defensa en profundidad: solo se reanuda lo que el checkpoint realmente espera
        if not pending or pending["kind"] != "quiz" or set(answers) != set(pending["question_ids"]):
            return
        self.store.log_event(onboarding_id, ACTOR_PERSON, onboarding_id, "quiz_submitted", {"answered": len(answers)}, self.clock())
        self._run(onboarding_id, Command(resume={str(k): int(v) for k, v in answers.items()}))

    # ---- los aprobadores ----------------------------------------------------------------------------------------------------
    def check_decision(self, onboarding_id: str, staff: dict | None, decision: str, comment: str | None, flags: dict | None) -> dict:
        record = self.store.onboarding(onboarding_id)
        pending = self.awaiting(onboarding_id)
        if not pending or pending["kind"] != "approval":
            raise NotAwaiting("Ahora mismo el flujo no espera ninguna aprobación.")
        stage = config.STAGE_BY_NUMBER[pending["stage"]]
        if not approver_allowed(stage, staff, record):
            raise Forbidden(f"Solo puede decidir esta etapa: {stage.approver_label}.")
        if decision not in ("approve", "reject"):
            raise OnboardingError("La decisión debe ser «approve» o «reject».")
        if decision == "reject" and not (comment or "").strip():
            raise OnboardingError("Un rechazo necesita un comentario para la persona incorporada.")
        flags = flags or {}
        if decision == "approve":
            if stage.number == 1 and not (flags.get("contract_received") and flags.get("payroll_docs_received")):
                raise OnboardingError("Para aprobar esta etapa, el contrato y la documentación de nómina deben figurar como recibidos.")
            if stage.number == 8 and not flags.get("accesses_confirmed"):
                raise OnboardingError("Para cerrar el onboarding hay que confirmar que los accesos están activos.")
        return pending

    def apply_decision(self, onboarding_id: str, staff_id: str, decision: str, comment: str | None, flags: dict | None) -> None:
        pending = self.awaiting(onboarding_id)
        if not pending or pending["kind"] != "approval":
            return  # no hay ninguna aprobación abierta: una decisión tardía o repetida no puede mover el flujo
        allowed = {"contract_received", "payroll_docs_received", "accesses_confirmed"}
        clean_flags = {key: bool(value) for key, value in (flags or {}).items() if key in allowed}
        self._run(onboarding_id, Command(resume={"decision": decision, "comment": redact(comment or "")[0], "actor_id": staff_id, "flags": clean_flags}))

    # ---- dudas ---------------------------------------------------------------------------------------------------------------
    def ask(self, onboarding_id: str, question: str) -> dict:
        record = self.store.onboarding(onboarding_id)
        clean, sensitive = redact(question)
        answer = knowledge.consult(clean, record["department"], record["site"], self.kb_dir)
        self.agent.act("consult_documents", onboarding_id, "question_answered" if answer.answered else "question_derived",
                       {"sources": list(answer.sources), "reason": answer.reason, "had_sensitive_data": bool(sensitive)})
        self.store.log_question(onboarding_id, clean, answer.answered, list(answer.sources), self.clock())
        if not answer.answered:
            for ashley in self.store.staff_with_role(config.ROLE_PEOPLE_MANAGER):
                self.agent.notify(onboarding_id, "staff", ashley["id"], "question_derived", record["current_stage"],
                                  f"{record['name']} tiene una duda que el material oficial no cubre: «{clean[:200]}»")
        message = answer.text
        if sensitive:
            message += " Por seguridad no he guardado los datos personales que has escrito: no los compartas por este canal."
        return {"answered": answer.answered, "answer": message, "sources": [
            {"ref": ref, "label": (knowledge.find_section(ref, self.kb_dir).label if knowledge.find_section(ref, self.kb_dir) else ref)} for ref in answer.sources],
            "derived_to": None if answer.answered else "Personas (Ashley Turner)"}

    # ---- vistas -------------------------------------------------------------------------------------------------------------
    def _stage_view(self, record: dict, progress: dict, now: datetime) -> dict:
        stage = config.STAGE_BY_NUMBER[progress["stage"]]
        deadline = parse(progress["deadline_at"]) or schedule.deadline_at(date.fromisoformat(record["start_date"]), stage.deadline_day, record["site"])
        return {"number": stage.number, "key": stage.key, "title": stage.title, "status": progress["status"], "exit_condition": stage.exit_condition,
                "approver": stage.approver_label, "requires_human_approval": stage.approver is not None, "has_comprehension_check": stage.quiz,
                "deadline_at": deadline.isoformat(), "completed_at": progress["completed_at"], "attempts": progress["attempts"],
                "rejections": progress["rejections"], "last_comment": progress["last_comment"],
                "overdue": progress["status"] != "completed" and now > deadline and progress["status"] == "active"}

    def _public_row(self, record: dict, now: datetime) -> dict:
        stages = [self._stage_view(record, p, now) for p in self.store.stages(record["id"])]
        current = next((s for s in stages if s["number"] == record["current_stage"]), stages[0])
        done = sum(1 for s in stages if s["status"] == "completed")
        awaiting = self.awaiting(record["id"]) if record["status"] != "creating" else None
        waiting_on = None
        if record["status"] == "completed":
            waiting_on = None
        elif awaiting and awaiting["kind"] == "quiz":
            waiting_on = "La persona incorporada (comprobación)"
        elif awaiting and awaiting["kind"] == "approval":
            waiting_on = current["approver"]
        overdue = bool(current["overdue"]) and record["status"] == "active"
        return {"id": record["id"], "name": record["name"], "position": record["position"], "department": record["department"], "site": record["site"],
                "manager_id": record["manager_id"], "status": record["status"], "current_stage": record["current_stage"],
                "current_stage_title": current["title"], "waiting_on": waiting_on, "overdue": overdue,
                "blocked": overdue and bool(awaiting and awaiting["kind"] == "approval"),
                "deadline_at": current["deadline_at"], "progress": {"completed": done, "total": len(stages)},
                "start_date": record["start_date"], "processing_error": record["processing_error"], "stages": stages}

    def board(self) -> list[dict]:
        now = self.clock()
        return [self._public_row(r, now) for r in self.store.onboardings()]

    def person_view(self, onboarding_id: str) -> dict:
        record = self.store.onboarding(onboarding_id)
        now = self.clock()
        view = self._public_row(record, now)
        manager = self.store.staff(record["manager_id"])
        view["manager"] = {"id": manager["id"], "name": manager["name"]} if manager else None
        view["paperwork"] = {k: bool(v) for k, v in self.store.paperwork(onboarding_id).items() if k != "onboarding_id"}
        view["awaiting"] = None
        view["presentation"] = None
        view["quiz"] = None
        stage = config.STAGE_BY_NUMBER[record["current_stage"]]
        if record["status"] == "active":
            awaiting = self.awaiting(onboarding_id)
            if awaiting:
                view["awaiting"] = {"kind": awaiting["kind"], "stage": awaiting["stage"]}
            sections = knowledge.stage_sections(stage, record["variant"], record["department"], record["site"], self.kb_dir)
            if sections:
                view["presentation"] = {"stage": stage.number, "title": stage.title, "sections": [
                    {"id": s.id, "title": s.title, "body": s.body, "source": s.label, "ref": s.ref} for s in sections]}
            state = self.store.quiz(onboarding_id)
            if state and stage.quiz and awaiting and awaiting["kind"] == "quiz":
                questions = [quiz.question_by_id(stage, record["variant"], qid, self.kb_dir) for qid in state["question_ids"]]
                view["quiz"] = {"attempt": state["attempt"] + 1, "passing_score": config.PASS_THRESHOLD, "last_score": state["last_score"],
                                "questions": [q.public() for q in questions],
                                "reinforce": [{"title": s.title, "body": s.body, "source": s.label} for ref in state["failed_sources"]
                                              if (s := knowledge.find_section(ref, self.kb_dir))]}
        progress = self.store.stage(onboarding_id, record["current_stage"])
        view["last_rejection_comment"] = progress["last_comment"] if progress["status"] == "active" and progress["rejections"] else None
        view["remaining"] = [s["title"] for s in view["stages"] if s["status"] != "completed"]
        return view

    def pending_for(self, staff: dict) -> list[dict]:
        """Aprobaciones que espera ESTA persona ahora mismo."""
        items = []
        for record in self.store.onboardings("active"):
            awaiting = self.awaiting(record["id"])
            if awaiting and awaiting["kind"] == "approval":
                stage = config.STAGE_BY_NUMBER[awaiting["stage"]]
                if approver_allowed(stage, staff, record):
                    row = self._public_row(record, self.clock())
                    items.append({**{k: row[k] for k in ("id", "name", "position", "department", "site", "overdue", "deadline_at")},
                                  "stage": stage.number, "stage_title": stage.title, "exit_condition": stage.exit_condition})
        return items

    # ---- seguimiento: recordatorios y escalados ----------------------------------------------------------------------------
    def sweep(self, now: datetime | None = None) -> list[dict]:
        """Revisa las incorporaciones activas: recordatorio 24 h antes del plazo (a la persona), escalado al responsable directo cuando una
        etapa vence, y escalado a Ashley cuando el retraso acumulado supera 3 días hábiles. Cada aviso se envía UNA vez por etapa."""
        now = now or self.clock()
        sent: list[dict] = []
        for record in self.store.onboardings("active"):
            stage = config.STAGE_BY_NUMBER[record["current_stage"]]
            progress = self.store.stage(record["id"], stage.number)
            deadline = parse(progress["deadline_at"])
            if not deadline or progress["status"] != "active":
                continue
            hours_left = (deadline - now).total_seconds() / 3600
            if 0 < hours_left <= config.REMINDER_HOURS_BEFORE and not progress["reminder_sent_at"]:
                self._send(record, stage, "reminder", "person", record["id"], now,
                           f"Recordatorio: tu etapa «{stage.title}» vence en menos de 24 horas.", "reminder_sent_at", sent)
            if now > deadline and not progress["overdue_notified_at"]:
                self._send(record, stage, "stage_overdue", "staff", record["manager_id"], now,
                           f"La etapa «{stage.title}» de {record['name']} superó su plazo.", "overdue_notified_at", sent)
            delay = schedule.business_days_between(deadline, now, record["site"]) if now > deadline else 0
            if delay > config.TOTAL_DELAY_DAYS_FOR_PEOPLE_MANAGER and not progress["delay_notified_at"]:
                for ashley in self.store.staff_with_role(config.ROLE_PEOPLE_MANAGER):
                    self._send(record, stage, "delay_over_3_days", "staff", ashley["id"], now,
                               f"{record['name']} acumula {delay} días hábiles de retraso (etapa «{stage.title}»).", "delay_notified_at", sent)
        return sent

    def _send(self, record: dict, stage: config.Stage, kind: str, rkind: str, rid: str, now: datetime, message: str, marker: str, sent: list) -> None:
        self.agent.notify(record["id"], rkind, rid, kind, stage.number, message)
        self.store.update_stage(record["id"], stage.number, **{marker: now.isoformat()})
        sent.append({"onboarding_id": record["id"], "kind": kind, "stage": stage.number, "to": f"{rkind}:{rid}"})
