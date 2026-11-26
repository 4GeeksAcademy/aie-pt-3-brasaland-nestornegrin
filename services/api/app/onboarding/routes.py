"""Endpoints del orquestador de onboarding corporativo. Los routers SOLO validan identidad/permiso y delegan: la lógica del agente vive en
`data/pipelines/onboarding/` (grafo LangGraph + checkpointer).

    POST /onboarding                      Personas da de alta una incorporación (rechaza puestos de restaurante) → 202; el agente arranca en segundo plano
    GET  /onboarding                      tablero de Personas: etapa, a quién se espera, bloqueadas (el responsable directo ve solo sus equipos)
    GET  /onboarding/me                   la persona incorporada: su progreso, el contenido de su etapa, la comprobación y lo que falta
    GET  /onboarding/approvals            aprobaciones que espera quien consulta
    GET  /onboarding/notifications        avisos de quien consulta (recordatorios, escalados, dudas derivadas)
    GET  /onboarding/{id}                 detalle (Personas, responsable directo o la propia persona)
    GET  /onboarding/{id}/events          auditoría: quién hizo qué (el agente figura como proceso automatizado)
    POST /onboarding/{id}/answers         la persona responde la comprobación → 202 (el agente avanza o refuerza en segundo plano)
    POST /onboarding/{id}/decision        aprueba o rechaza un punto humano; solo quien tiene el rol y el departamento adecuados
    POST /onboarding/{id}/questions       duda: se responde solo con el material oficial (con fuente) o se deriva a Personas
    POST /onboarding/sweep                recordatorios y escalados por plazos (Personas)

Identidad: el JWT identifica a un usuario por su correo; ese correo se cruza con el directorio de personas (`staff`) o con la propia
incorporación. Que alguien sea `admin` de la plataforma NO le da poder de aprobar: la aprobación depende del directorio de Personas.
El trabajo del agente corre en `BackgroundTasks`; la verdad está en el checkpoint (SQLite o PostgreSQL), no en el proceso."""
from __future__ import annotations

import os
from datetime import date
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from data.pipelines.onboarding import config
from data.pipelines.onboarding.runner import OnboardingEngine, OnboardingError

from ..auth.dependencies import get_current_user
from ..access.permissions import is_platform_admin

_engine: OnboardingEngine | None = None


def get_engine() -> OnboardingEngine:
    global _engine
    if _engine is None:
        from data.pipelines.onboarding.checkpoint import build_checkpointer
        from data.pipelines.onboarding.seed import seed
        from data.pipelines.onboarding.store import OnboardingStore

        _engine = OnboardingEngine(OnboardingStore(os.environ.get("ONBOARDING_DB") or None),
                                   build_checkpointer(os.environ.get("ONBOARDING_CHECKPOINT_DB") or None))
        if os.environ.get("ONBOARDING_SEED") == "1":
            seed(_engine)
    return _engine


def set_engine(engine: OnboardingEngine | None) -> None:
    """Para las pruebas: inyecta un motor con bases temporales."""
    global _engine
    _engine = engine


class NewOnboarding(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    position: str = Field(min_length=2, max_length=80)
    department: str = Field(min_length=2, max_length=60)
    site: str = Field(min_length=2, max_length=20)
    manager_id: str = Field(min_length=1, max_length=40)
    start_date: date


class _Out(BaseModel):
    model_config = ConfigDict(extra="allow")  # el motor ya entrega solo estados; `extra` conserva los campos de detalle (etapas, vistas)


class CreatedOut(_Out):
    id: str
    status: str


class AcceptedOut(_Out):
    accepted: bool


class BoardRowOut(_Out):
    id: str
    name: str
    position: str
    department: str
    site: str
    manager_id: str
    status: str
    current_stage: int
    current_stage_title: str
    waiting_on: str | None = None
    overdue: bool
    blocked: bool
    deadline_at: str
    progress: dict[str, int]
    stages: list[dict]


class PersonViewOut(BoardRowOut):
    remaining: list[str] = []
    awaiting: dict | None = None
    presentation: dict | None = None
    quiz: dict | None = None
    last_rejection_comment: str | None = None


class PendingApprovalOut(_Out):
    id: str
    name: str
    stage: int
    stage_title: str
    exit_condition: str


class NoticeOut(_Out):
    id: int
    kind: str
    message: str
    stage: int | None = None


class EventOut(_Out):
    id: int
    ts: str
    actor_type: str
    actor_id: str
    action: str
    detail: dict


class SweepOut(_Out):
    sent: list[dict]


class SourceOut(_Out):
    ref: str
    label: str


class ReplyOut(_Out):
    answered: bool
    answer: str
    sources: list[SourceOut]
    derived_to: str | None = None


class AnswersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: dict[str, int]


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=500)
    contract_received: bool = False
    payroll_docs_received: bool = False
    accesses_confirmed: bool = False


class QuestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=3, max_length=500)


def _fail(error: OnboardingError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.message)


def create_router() -> APIRouter:
    router = APIRouter(prefix="/onboarding", tags=["onboarding"])

    def who(user, engine: OnboardingEngine) -> dict:
        """Quién consulta: persona del directorio (`staff`), persona incorporada, o ninguna de las dos."""
        email = str(user.email).lower()
        return {"staff": engine.store.staff_by_email(email), "onboarding": engine.store.onboarding_by_email(email),
                "platform_admin": is_platform_admin(user)}

    def is_people(identity: dict) -> bool:
        s = identity["staff"]
        return bool(s and s["department"] == "Personas" and s["role"] in (config.ROLE_PEOPLE_TEAM, config.ROLE_PEOPLE_MANAGER))

    def can_see(identity: dict, record: dict) -> bool:
        s, own = identity["staff"], identity["onboarding"]
        return is_people(identity) or bool(s and s["id"] == record["manager_id"]) or bool(own and own["id"] == record["id"])

    def load(onboarding_id: str, identity: dict, engine: OnboardingEngine) -> dict:
        record = engine.store.onboarding(onboarding_id)
        if record is None or not can_see(identity, record):
            raise HTTPException(status_code=404, detail="Onboarding no encontrado")  # no revela si existe
        return record

    @router.post("", status_code=202, response_model=CreatedOut)
    def create(body: NewOnboarding, background: BackgroundTasks, user=Depends(get_current_user)):
        engine = get_engine()
        identity = who(user, engine)
        if not is_people(identity):
            raise HTTPException(status_code=403, detail="Solo el equipo de Personas puede iniciar un onboarding.")
        try:
            record = engine.register(identity["staff"]["id"], body.model_dump())
        except OnboardingError as error:
            raise _fail(error)
        background.add_task(engine.start, record["id"])
        return {"id": record["id"], "status": "creating"}

    @router.get("", response_model=list[BoardRowOut])
    def board(user=Depends(get_current_user)):
        engine = get_engine()
        identity = who(user, engine)
        rows = engine.board()
        if is_people(identity):
            return rows
        if identity["staff"] and identity["staff"]["role"] == config.ROLE_MANAGER:
            return [r for r in rows if r["manager_id"] == identity["staff"]["id"]]
        raise HTTPException(status_code=403, detail="No tienes acceso al tablero de onboarding.")

    @router.get("/me", response_model=PersonViewOut)
    def mine(user=Depends(get_current_user)):
        engine = get_engine()
        own = who(user, engine)["onboarding"]
        if own is None:
            raise HTTPException(status_code=404, detail="No tienes un onboarding asignado.")
        return engine.person_view(own["id"])

    @router.get("/approvals", response_model=list[PendingApprovalOut])
    def approvals(user=Depends(get_current_user)):
        engine = get_engine()
        staff = who(user, engine)["staff"]
        return engine.pending_for(staff) if staff else []

    @router.get("/notifications", response_model=list[NoticeOut])
    def notifications(user=Depends(get_current_user)):
        engine = get_engine()
        identity = who(user, engine)
        if identity["staff"]:
            return engine.store.notifications("staff", identity["staff"]["id"])
        if identity["onboarding"]:
            return engine.store.notifications("person", identity["onboarding"]["id"])
        return []

    @router.post("/sweep", response_model=SweepOut)
    def sweep(user=Depends(get_current_user)):
        engine = get_engine()
        if not is_people(who(user, engine)):
            raise HTTPException(status_code=403, detail="Solo Personas puede ejecutar el seguimiento de plazos.")
        return {"sent": engine.sweep()}

    @router.get("/{onboarding_id}", response_model=PersonViewOut)
    def detail(onboarding_id: str, user=Depends(get_current_user)):
        engine = get_engine()
        load(onboarding_id, who(user, engine), engine)
        return engine.person_view(onboarding_id)

    @router.get("/{onboarding_id}/events", response_model=list[EventOut])
    def events(onboarding_id: str, user=Depends(get_current_user)):
        engine = get_engine()
        identity = who(user, engine)
        load(onboarding_id, identity, engine)
        if not is_people(identity):
            raise HTTPException(status_code=403, detail="La auditoría es solo para Personas.")
        return engine.store.events(onboarding_id)

    @router.post("/{onboarding_id}/answers", status_code=202, response_model=AcceptedOut)
    def answers(onboarding_id: str, body: AnswersIn, background: BackgroundTasks, user=Depends(get_current_user)):
        engine = get_engine()
        identity = who(user, engine)
        if not identity["onboarding"] or identity["onboarding"]["id"] != onboarding_id:
            raise HTTPException(status_code=403, detail="Solo la persona incorporada responde su comprobación.")
        try:
            engine.check_answers(onboarding_id, body.answers)
        except OnboardingError as error:
            raise _fail(error)
        background.add_task(engine.apply_answers, onboarding_id, body.answers)
        return {"accepted": True}

    @router.post("/{onboarding_id}/decision", status_code=202, response_model=AcceptedOut)
    def decision(onboarding_id: str, body: DecisionIn, background: BackgroundTasks, user=Depends(get_current_user)):
        engine = get_engine()
        identity = who(user, engine)
        if engine.store.onboarding(onboarding_id) is None:
            raise HTTPException(status_code=404, detail="Onboarding no encontrado")
        flags = {"contract_received": body.contract_received, "payroll_docs_received": body.payroll_docs_received,
                 "accesses_confirmed": body.accesses_confirmed}
        try:
            engine.check_decision(onboarding_id, identity["staff"], body.decision, body.comment, flags)
        except OnboardingError as error:
            raise _fail(error)
        background.add_task(engine.apply_decision, onboarding_id, identity["staff"]["id"], body.decision, body.comment, flags)
        return {"accepted": True}

    @router.post("/{onboarding_id}/questions", response_model=ReplyOut)
    def question(onboarding_id: str, body: QuestionIn, user=Depends(get_current_user)):
        engine = get_engine()
        identity = who(user, engine)
        if not identity["onboarding"] or identity["onboarding"]["id"] != onboarding_id:
            raise HTTPException(status_code=403, detail="Solo la persona incorporada puede hacer preguntas en su onboarding.")
        return engine.ask(onboarding_id, body.question)

    return router
