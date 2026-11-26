"""Endpoints de proveedores y contratos. Los routers SOLO validan identidad/permiso y delegan: la lógica vive en `data/pipelines/supplier_contracts/`
(supervisor + especialistas). Identidad: el correo del JWT se cruza con el directorio (Felipe, Mariana, Lucía); ser `admin` de la plataforma NO
da poder de aprobar. Datos sensibles: nunca salen por aquí (se redactan al ingerir).

    GET  /supplier-contracts/suppliers                    proveedores del briefing y si tienen contrato
    POST /supplier-contracts/seed                         genera e ingiere los datos de prueba (contratos PDF + histórico) y calcula alertas
    GET  /supplier-contracts/alerts                       alertas de precio, vencimiento y preaviso (a Compras y Operaciones)
    POST /supplier-contracts/alerts/scan                  recalcula alertas (idempotente)
    GET  /supplier-contracts/suppliers/{id}/prices        histórico con su fila de origen
    GET  /supplier-contracts/suppliers/{id}/contract      términos con cláusula y página
    POST /supplier-contracts/ask                          pregunta en lenguaje natural → el supervisor consulta a los especialistas
    POST /supplier-contracts/brief                        brief de renegociación (con borrador opcional pendiente de aprobación)
    POST /supplier-contracts/notices                      registra un preaviso escrito o la prueba de un índice
    GET  /supplier-contracts/communications               borradores y su estado de aprobación
    POST /supplier-contracts/communications/{id}/decision aprueba o rechaza (solo el aprobador exigido)
    POST /supplier-contracts/communications/{id}/send     orden de envío (solo Felipe, solo si TODAS las aprobaciones constan)
    GET  /supplier-contracts/audit/events                 quién (qué agente o persona) hizo qué
    GET  /supplier-contracts/audit/messages               mensajes entre agentes (ya redactados)"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from data.pipelines.supplier_contracts import config
from data.pipelines.supplier_contracts.approvals import ApprovalError
from data.pipelines.supplier_contracts.engine import SupplierEngine
from data.pipelines.supplier_contracts.schemas import ContractResponse, PriceResponse, SupervisorReply
from data.pipelines.supplier_contracts.store import Store

from ..auth.dependencies import get_current_user

_engine: SupplierEngine | None = None


def get_engine() -> SupplierEngine:
    global _engine
    if _engine is None:
        _engine = SupplierEngine(Store(os.environ.get("SUPPLIER_CONTRACTS_DB") or None))
        _engine.store.seed_staff()
        if os.environ.get("SUPPLIER_CONTRACTS_SEED") == "1":
            _engine.seed(date.today())
    return _engine


def set_engine(engine: SupplierEngine | None) -> None:
    """Para las pruebas: inyecta un motor con base temporal."""
    global _engine
    _engine = engine


class _Out(BaseModel):
    model_config = ConfigDict(extra="allow")


class SupplierOut(_Out):
    id: str
    name: str
    country: str
    category: str
    currency: str
    contract_id: str | None = None
    has_contract: bool


class SeedOut(_Out):
    load_date: str
    price_rows: int
    contracts: list[dict]
    alerts: int


class AlertOut(_Out):
    id: int
    key: str
    kind: str
    supplier_id: str
    contract_id: str | None = None
    stage: int | None = None
    as_of: str
    message: str
    detail: dict
    recipients: list[str]
    created_at: str


class ApprovalOut(_Out):
    role: str
    staff_id: str
    decision: str
    comment: str | None = None
    ts: str


class CommunicationOut(_Out):
    id: int
    supplier_id: str
    contract_id: str | None = None
    subject: str
    body: str
    status: str
    required_roles: list[str]
    missing_roles: list[str]
    approvals: list[ApprovalOut]
    created_by: str
    created_at: str


class EventOut(_Out):
    id: int
    ts: str
    actor_type: str
    actor_id: str
    action: str
    subject: str
    detail: dict


class MessageOut(_Out):
    id: int
    ts: str
    request_id: str
    sender: str
    recipient: str
    payload: dict


class NoticeOut(_Out):
    id: int
    supplier_id: str
    kind: str


class AskIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=3, max_length=500)


class BriefIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supplier_id: str = Field(pattern=r"^BR-S\d{2}$")
    draft_message: bool = False


class NoticeIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    supplier_id: str = Field(pattern=r"^BR-S\d{2}$")
    kind: Literal["price_increase_notice", "index_evidence"]
    ref: str = Field(min_length=1, max_length=60, description="referencia del aviso o, para index_evidence, el % que subió el índice en el trimestre")


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=500)


def _fail(error: ApprovalError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.message)


def create_router() -> APIRouter:
    router = APIRouter(prefix="/supplier-contracts", tags=["supplier-contracts"])

    def staff_of(user, engine: SupplierEngine) -> dict | None:
        return engine.store.staff_by_email(str(user.email))

    def need_staff(user, engine: SupplierEngine) -> dict:
        staff = staff_of(user, engine)
        if staff is None:
            raise HTTPException(status_code=403, detail="Solo Compras y Operaciones (directorio) acceden a proveedores y contratos.")
        return staff

    def need_role(user, engine: SupplierEngine, *roles: str) -> dict:
        staff = need_staff(user, engine)
        if staff["role"] not in roles:
            raise HTTPException(status_code=403, detail="Tu rol no puede hacer esta operación.")
        return staff

    def need_data(engine: SupplierEngine) -> None:
        if engine.load_date is None:
            raise HTTPException(status_code=409, detail="Aún no hay datos cargados: ejecuta POST /supplier-contracts/seed.")

    @router.get("/suppliers", response_model=list[SupplierOut])
    def suppliers(user=Depends(get_current_user)):
        engine = get_engine()
        need_staff(user, engine)
        return engine.suppliers()

    @router.post("/seed", response_model=SeedOut)
    def seed(user=Depends(get_current_user)):
        engine = get_engine()
        need_role(user, engine, config.ROLE_OPS_DIRECTOR, config.ROLE_PROCUREMENT)
        today = date.today()
        result = engine.seed(today, Path(os.environ.get("SUPPLIER_CONTRACTS_DATA_DIR") or config.DEFAULT_DATA_DIR))
        return {"load_date": today.isoformat(), "price_rows": result["price_rows"], "contracts": result["contracts"], "alerts": len(engine.alerts.listing())}

    @router.get("/alerts", response_model=list[AlertOut])
    def alerts(user=Depends(get_current_user)):
        engine = get_engine()
        staff = need_staff(user, engine)
        return [a for a in engine.alerts.listing() if staff["id"] in a["recipients"]] if staff["role"] == config.ROLE_PROCUREMENT or staff["id"] in config.ALERT_RECIPIENTS \
            else engine.alerts.listing()

    @router.post("/alerts/scan", response_model=list[AlertOut])
    def scan(user=Depends(get_current_user)):
        engine = get_engine()
        need_role(user, engine, config.ROLE_OPS_DIRECTOR, config.ROLE_PROCUREMENT)
        need_data(engine)
        return engine.alerts.scan(engine.load_date)

    @router.get("/suppliers/{supplier_id}/prices", response_model=PriceResponse)
    def prices(supplier_id: str, user=Depends(get_current_user)):
        engine = get_engine()
        need_staff(user, engine)
        need_data(engine)
        if supplier_id not in config.SUPPLIER_BY_ID:
            raise HTTPException(status_code=404, detail="Proveedor no encontrado")
        return engine.price_view(supplier_id)

    @router.get("/suppliers/{supplier_id}/contract", response_model=ContractResponse)
    def contract(supplier_id: str, user=Depends(get_current_user)):
        engine = get_engine()
        need_staff(user, engine)
        need_data(engine)
        if supplier_id not in config.SUPPLIER_BY_ID:
            raise HTTPException(status_code=404, detail="Proveedor no encontrado")
        return engine.contract_view(supplier_id)

    @router.post("/ask", response_model=SupervisorReply)
    def ask(body: AskIn, user=Depends(get_current_user)):
        engine = get_engine()
        need_staff(user, engine)
        need_data(engine)
        return engine.ask(body.question)

    @router.post("/brief", response_model=SupervisorReply)
    def brief(body: BriefIn, user=Depends(get_current_user)):
        engine = get_engine()
        need_role(user, engine, config.ROLE_OPS_DIRECTOR, config.ROLE_PROCUREMENT)
        need_data(engine)
        if body.supplier_id not in config.SUPPLIER_BY_ID:
            raise HTTPException(status_code=404, detail="Proveedor no encontrado")
        return engine.brief(body.supplier_id, draft_message=body.draft_message)

    @router.post("/notices", response_model=NoticeOut, status_code=201)
    def notice(body: NoticeIn, user=Depends(get_current_user)):
        engine = get_engine()
        staff = need_role(user, engine, config.ROLE_OPS_DIRECTOR, config.ROLE_PROCUREMENT)
        if body.supplier_id not in config.SUPPLIER_BY_ID:
            raise HTTPException(status_code=404, detail="Proveedor no encontrado")
        if body.kind == "index_evidence":
            try:
                float(body.ref)
            except ValueError:
                raise HTTPException(status_code=422, detail="Para index_evidence, `ref` es el % de subida del índice (un número).")
        nid = engine.store.add_notice(body.supplier_id, body.kind, body.ref)
        engine.store.event("staff", staff["id"], "notice_recorded", body.supplier_id, {"kind": body.kind})
        return {"id": nid, "supplier_id": body.supplier_id, "kind": body.kind}

    @router.get("/communications", response_model=list[CommunicationOut])
    def communications(user=Depends(get_current_user)):
        engine = get_engine()
        need_staff(user, engine)
        return engine.approvals.listing()

    @router.post("/communications/{communication_id}/decision", response_model=CommunicationOut)
    def decision(communication_id: int, body: DecisionIn, user=Depends(get_current_user)):
        engine = get_engine()
        staff = staff_of(user, engine)
        try:
            return engine.approvals.decide(communication_id, staff, body.decision, body.comment)
        except ApprovalError as error:
            raise _fail(error)

    @router.post("/communications/{communication_id}/send", response_model=CommunicationOut)
    def send(communication_id: int, user=Depends(get_current_user)):
        engine = get_engine()
        try:
            return engine.approvals.send(communication_id, staff_of(user, engine))
        except ApprovalError as error:
            raise _fail(error)

    @router.get("/audit/events", response_model=list[EventOut])
    def audit_events(user=Depends(get_current_user)):
        engine = get_engine()
        need_role(user, engine, config.ROLE_OPS_DIRECTOR, config.ROLE_CEO)
        return engine.store.events(300)

    @router.get("/audit/messages", response_model=list[MessageOut])
    def audit_messages(user=Depends(get_current_user)):
        engine = get_engine()
        need_role(user, engine, config.ROLE_OPS_DIRECTOR, config.ROLE_CEO)
        return engine.store.messages()[-300:]

    return router
