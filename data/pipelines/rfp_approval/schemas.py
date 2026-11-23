"""La respuesta humana se VALIDA antes de entrar al grafo: si no es válida, el checkpoint no se toca."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from data.pipelines.rfp_intake.departments import DEPARTMENTS
from data.pipelines.rfp_response.rules import check_setup_times

from . import config


class InvalidDecision(ValueError):
    """La respuesta humana no es válida (o no corresponde ahora). `code` ayuda a la API a elegir 409/422."""

    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


class Decision(BaseModel):
    department_id: str
    action: str
    approver: str
    comment: str = ""
    submitted_by: str | None = None  # usuario autenticado que registró la decisión (auditoría; el responsable lo declara `approver`)
    figures: dict[str, str] = Field(default_factory=dict)  # cifras estructuradas (p. ej. costo_insumos_por_cubierto_usd) para el arbitraje

    @field_validator("action")
    @classmethod
    def _action(cls, v: str) -> str:
        if v not in config.ACTIONS:
            raise ValueError(f"Acción inválida «{v}»: usa {', '.join(config.ACTIONS)}.")
        return v

    @field_validator("approver", "comment")
    @classmethod
    def _strip(cls, v: str) -> str:
        return " ".join(v.split())

    @field_validator("figures")
    @classmethod
    def _numeric(cls, v: dict[str, str]) -> dict[str, str]:
        for key, value in v.items():
            if not re.fullmatch(r"[A-Za-z0-9_]{1,60}", key) or not re.fullmatch(r"\$?\s*\d[\d.,]*", str(value).strip()):
                raise ValueError(f"La cifra «{key}: {value}» no es numérica.")
        return {k: str(x).strip() for k, x in v.items()}

    @model_validator(mode="after")
    def _comment_required(self):
        if self.action != config.APPROVE and len(self.comment) < config.MIN_COMMENT_CHARS:
            raise ValueError(f"Para {self.action} indica qué debe corregirse (mínimo {config.MIN_COMMENT_CHARS} caracteres): "
                             "ese comentario es el feedback del generador.")
        return self


def validate_decision(raw: dict, *, department_id: str, waiting: bool, escalated: bool = False, draft_text: str = "") -> Decision:
    """Valida contra el estado actual. Lanza `InvalidDecision`; si pasa, la decisión puede reanudar el grafo."""
    try:
        decision = Decision.model_validate(raw)
    except ValidationError as exc:
        raise InvalidDecision(exc.errors()[0]["msg"].removeprefix("Value error, "), "schema") from exc
    if decision.department_id != department_id:
        raise InvalidDecision(f"La decisión es de «{decision.department_id}» pero se aplica a «{department_id}».", "department")
    if not waiting:
        raise InvalidDecision(f"«{department_id}» no está esperando una aprobación ahora.", "not_waiting")
    allowed = {config.owner_of(department_id)}
    if escalated:
        allowed.add(config.ARBITER_NAME)  # límite de rondas agotado: la dueña del ticket (árbitro fijo) también puede decidir
    if decision.approver not in allowed:
        raise InvalidDecision(f"Solo {' o '.join(sorted(allowed))} puede decidir por «{department_id}» (BRIEFING §2.1/§6); "
                              f"recibido: «{decision.approver}».", "approver")
    if decision.action == config.APPROVE and department_id != config.CEO_ID and check_setup_times(draft_text):
        raise InvalidDecision("El borrador promete montaje/entrega en menos de 10 días hábiles (BRIEFING §5, trigger setup-sla-breach): "
                              "no puede aprobarse; pide cambios.", "guardrail")
    return decision


__all__ = ["DEPARTMENTS", "Decision", "InvalidDecision", "validate_decision"]
