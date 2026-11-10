"""`AgentMemory`: une política, almacén y clasificador en el flujo propuesta -> confirmación -> consolidación.

Reglas que este módulo hace cumplir (cada una tiene su prueba en `tests/pipelines/test_agent_memory.py`):
  * `store.activate_memory()` solo se llama desde `resolve_pending()` tras un APPROVE o EDIT clasificado con confianza
    suficiente: no existe otro camino de escritura.
  * Una sola propuesta pendiente por conversación (índice único + comprobación antes de abrir otra).
  * Silencio, cambio de tema, ambigüedad, error del clasificador, edición inválida o límite de ritmo => se DESCARTA.
  * Todo pasa por `memory_events` (solo-añadir): propuesta, decisión, escritura, descarte.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Callable

from .llm import classify_intent
from .models import (
    PROPOSAL_APPROVED,
    PROPOSAL_DISCARDED,
    PROPOSAL_EDITED,
    PROPOSAL_REJECTED,
    ConsolidationReport,
    Decision,
    Intent,
    MemoryProposal,
    ProposalOutcome,
    Resolution,
)
from .policy import CATEGORY_LABELS, fact_issues, validate_proposal
from .store import PendingProposalExists, SqliteMemoryStore

logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.8  # por debajo, la clasificación cuenta como ambigua
MAX_APPROVALS_PER_HOUR = 5  # por conversación: frena a quien intente llenar la memoria
MAX_APPROVALS_PER_DAY = 20  # por actor

MESSAGES = {
    "es": {
        "question": "¿Quieres que recuerde esto para la próxima vez?",
        "reply": "Responde «sí», «no» o dime cómo corregirlo.",
        "replaces": "Reemplazaría lo guardado: «{old}»",
        "approved": "Listo, lo guardé: {fact}",
        "edited": "Listo, guardé tu versión: {fact}",
        "rejected": "Entendido, no lo guardo.",
        "discarded": "No me quedó claro si querías guardarlo, así que lo descarté. Si lo quieres, dímelo de nuevo.",
        "invalid_edit": "No puedo guardar esa versión, así que descarté la propuesta.",
        "rate_limited": "Llegaste al límite de recuerdos por ahora, así que descarté la propuesta.",
    },
    "en": {
        "question": "Do you want me to remember this for next time?",
        "reply": "Reply \"yes\", \"no\", or tell me how to fix it.",
        "replaces": "It would replace what is saved: \"{old}\"",
        "approved": "Done, I saved it: {fact}",
        "edited": "Done, I saved your version: {fact}",
        "rejected": "Understood, I won't save it.",
        "discarded": "It wasn't clear whether you wanted to save it, so I discarded it. Tell me again if you do.",
        "invalid_edit": "I can't save that version, so I discarded the proposal.",
        "rate_limited": "You've reached the memory limit for now, so I discarded the proposal.",
    },
}


def render_question(proposal: MemoryProposal, replaced_fact: str | None = None) -> str:
    """Texto que se añade a la respuesta. Muestra EXACTAMENTE lo que se guardaría (nada oculto)."""
    text = MESSAGES[proposal.language]
    label = CATEGORY_LABELS[proposal.language][proposal.category]
    lines = [text["question"], f"• {proposal.location} · {label}: {proposal.fact}"]
    if replaced_fact:
        lines.append(text["replaces"].format(old=replaced_fact))
    lines.append(text["reply"])
    return "\n".join(lines)


class AgentMemory:
    def __init__(self, store: SqliteMemoryStore | None = None,
                 classify_fn: Callable[[dict, str], Decision] = classify_intent):
        self.store = store or SqliteMemoryStore()
        self.classify_fn = classify_fn

    # --- lectura --------------------------------------------------------------------------------------------
    def recall(self, question: str) -> list[dict]:
        return self.store.recall(question)

    # --- propuesta ------------------------------------------------------------------------------------------
    def propose(self, raw: dict | None, *, conversation_id: str, message: str, actor: str,
                run_id: str | None = None) -> ProposalOutcome | None:
        """Convierte la propuesta del modelo en una propuesta PENDIENTE, o la descarta (y lo registra). Nunca escribe memoria."""
        if not raw or not raw.get("aplica"):
            return None  # el caso normal: nada que recordar
        proposal, issues = validate_proposal(raw, message)
        if proposal is None:
            self.store.add_event("proposal_rejected_by_policy", actor="system:policy", conversation_id=conversation_id,
                                 run_id=run_id, detail={"issues": issues, "proposed_by": actor})
            return None
        if self.store.get_pending(conversation_id):
            self.store.add_event("proposal_skipped_pending_exists", actor="system:policy",
                                 conversation_id=conversation_id, run_id=run_id, detail={"fact": proposal.fact})
            return None
        existing = self.store.find_active(proposal.location, proposal.category, proposal.topic)
        if existing and existing["fact"].strip().lower() == proposal.fact.strip().lower():
            return None  # ya está guardado tal cual: no se molesta al usuario
        try:
            proposal_id = self.store.create_proposal(
                conversation_id, proposal, origin_message=redact(message), run_id=run_id, actor=f"agent (turno de {actor})",
                replaces_id=existing["id"] if existing else None)
        except PendingProposalExists:
            return None
        self.store.add_event("proposal_created", actor="agent", conversation_id=conversation_id, proposal_id=proposal_id,
                             run_id=run_id, detail={"location": proposal.location, "category": proposal.category,
                                                    "fact": proposal.fact, "origin_message": redact(message),
                                                    "replaces": existing["id"] if existing else None})
        return ProposalOutcome(proposal_id, proposal, render_question(proposal, existing["fact"] if existing else None),
                               existing["id"] if existing else None)

    # --- decisión del usuario -------------------------------------------------------------------------------
    def resolve_pending(self, *, conversation_id: str, message: str, actor: str,
                        run_id: str | None = None) -> Resolution | None:
        """Evalúa `message` contra la propuesta pendiente de la conversación (si la hay). Solo aquí se escribe memoria."""
        pending = self.store.get_pending(conversation_id)
        if pending is None:
            return None
        language = pending["language"]
        try:
            decision = self.classify_fn(pending, message)
        except Exception:  # noqa: BLE001 - si el clasificador falla, la propuesta se descarta: nunca se asume aprobación
            logger.exception("Falló el clasificador de intención; la propuesta se descarta")
            decision = Decision(Intent.AMBIGUOUS)
        intent = decision.intent if decision.confidence >= MIN_CONFIDENCE else Intent.AMBIGUOUS
        confidence_detail = {"intent": decision.intent.value, "confidence": decision.confidence,
                             "decision_message": redact(message)}

        def finish(status: str, event: str, kind: str, notice_key: str, *, reason: str = "", memory_id=None,
                   final_fact=None, remainder: str = "") -> Resolution:
            self.store.resolve_proposal(pending["id"], status, decision=kind, decision_message=redact(message), actor=actor,
                                        reason=reason, final_fact=final_fact, memory_id=memory_id)
            self.store.add_event(event, actor=actor, conversation_id=conversation_id, proposal_id=pending["id"],
                                 memory_id=memory_id, run_id=run_id,
                                 detail={**confidence_detail, "reason": reason, "final_fact": final_fact})
            notice = MESSAGES[language][notice_key].format(fact=final_fact or "")
            return Resolution(kind, notice, remainder, pending["id"], reason, memory_id, language)

        if intent is Intent.REJECT:
            return finish(PROPOSAL_REJECTED, "proposal_rejected", "rejected", "rejected",
                          remainder=_safe_remainder(decision.remainder, message))
        if intent is Intent.AMBIGUOUS:
            # El usuario cambió de tema o no fue claro: la propuesta se descarta y su mensaje se atiende como nuevo.
            return finish(PROPOSAL_DISCARDED, "proposal_discarded", "discarded", "discarded",
                          reason="ambigua_o_cambio_de_tema", remainder=message.strip())

        final_fact = pending["fact"] if intent is Intent.APPROVE else (decision.edited_fact or "")
        if intent is Intent.EDIT:
            issues = fact_issues(final_fact, message)
            if issues:  # la edición también pasa por la política (el usuario puede equivocarse o ser un atacante)
                return finish(PROPOSAL_DISCARDED, "proposal_discarded", "discarded", "invalid_edit",
                              reason="edicion_rechazada_por_politica: " + ", ".join(issues),
                              remainder=_safe_remainder(decision.remainder, message))
        now = self.store.now()
        if (self.store.count_approvals_since(now - timedelta(hours=1), conversation_id=conversation_id)
                >= MAX_APPROVALS_PER_HOUR
                or self.store.count_approvals_since(now - timedelta(days=1), actor=actor) >= MAX_APPROVALS_PER_DAY):
            return finish(PROPOSAL_DISCARDED, "proposal_discarded", "discarded", "rate_limited",
                          reason="limite_de_ritmo", remainder=_safe_remainder(decision.remainder, message))

        memory_id, _ = self.store.activate_memory(pending, final_fact, actor=actor)
        status, kind, key = ((PROPOSAL_APPROVED, "approved", "approved") if intent is Intent.APPROVE
                             else (PROPOSAL_EDITED, "edited", "edited"))
        resolution = finish(status, "memory_written", kind, key, memory_id=memory_id, final_fact=final_fact,
                            remainder=_safe_remainder(decision.remainder, message))
        self.consolidate()  # tras cada escritura: la memoria nunca crece sin pasar por la limpieza
        return resolution

    def consolidate(self) -> ConsolidationReport:
        return self.store.consolidate()


def _safe_remainder(remainder: str, message: str) -> str:
    """El resto del mensaje lo extrae el clasificador; no puede ser más largo que el mensaje original."""
    remainder = (remainder or "").strip()
    return remainder if remainder and len(remainder) <= len(message.strip()) else ""


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_DIGITS = re.compile(r"(?:\+?\d[\s().-]?){7,}")


def redact(text: str, limit: int = 500) -> str:
    """Los mensajes se guardan en el registro de auditoría (el BRIEFING pide rastro de la propuesta), pero sin correos
    ni teléfonos y con tope de tamaño."""
    return _DIGITS.sub("[número]", _EMAIL.sub("[correo]", text)).strip()[:limit]
