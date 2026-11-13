"""Ultimate document synthesizer: consolida las secciones APROBADAS en la propuesta económica final.

Es determinista a propósito: un documento que va al cliente no debe contener texto que nadie aprobó. Solo ensambla lo aprobado,
añade la validez de la oferta (BRIEFING §5: 30 días desde su emisión) y un cuadro de aprobaciones, y verifica con el evaluador de
cumplimiento de la Parte 2 que el documento consolidado respete los lineamientos del §5 (cierra en fallo, no en silencio)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from data.pipelines.rfp_intake.departments import DEPARTMENT_IDS, DEPARTMENTS
from data.pipelines.rfp_response import agents as part2_agents
from data.pipelines.rfp_response.rules import evaluate_compliance

from . import config


class FinalDocumentError(RuntimeError):
    pass


def build_final_document(ticket_id: int, handoff: dict, sections: dict[str, dict], ceo: dict | None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    missing = [d for d in DEPARTMENT_IDS if d in sections and sections[d].get("approval_status") != config.APPROVAL_APPROVED]
    if missing:
        raise FinalDocumentError(f"No se puede generar el documento final: faltan aprobaciones de {', '.join(missing)}.")
    ordered = [d for d in DEPARTMENT_IDS if d in sections]
    allowed: set[str] = set()
    for d in ordered:
        allowed |= part2_agents.allowed_numbers(part2_agents.generator_payload(handoff, d))
    body = "\n\n".join(sections[d]["draft_content"] for d in ordered)
    check = evaluate_compliance(body, config.OWNER_DEPARTMENT, allowed)
    if not check["pass"]:
        raise FinalDocumentError("El documento consolidado incumple los lineamientos del BRIEFING §5: "
                                 + "; ".join(f"{v['rule_id']}: {v['message']}" for v in check["violations"]))
    meta = handoff.get("metadata", {})
    value = (ceo or {}).get("estimated_annual_value_usd")
    issued, until = now.date(), (now + timedelta(days=config.part2.OFFER_VALIDITY_DAYS)).date()
    lines = [f"# Propuesta económica — {meta.get('client_name') or 'Cliente'}", "",
             f"**RFP:** {handoff.get('rfp_id')} · **Ticket:** #{ticket_id} · **Emitida:** {issued.isoformat()}",
             f"**Validez de la oferta:** {config.part2.OFFER_VALIDITY_DAYS} días desde su emisión (hasta {until.isoformat()}).", "",
             "## Resumen de la solicitud", "",
             f"- Cliente: {meta.get('client_name') or 'No indicado'} · {meta.get('location') or 'ubicación no indicada'}",
             f"- Servicio: {meta.get('service_type') or 'No indicado'}", f"- Alcance: {meta.get('scope') or 'No indicado'}",
             f"- Fecha límite de respuesta: {meta.get('deadline') or 'No indicada'}",
             f"- Valor anual estimado: {f'{value:,.0f} USD' if value else 'no determinado'}", ""]
    for d in ordered:
        lines += [f"## {DEPARTMENTS[d].name}", "", sections[d]["draft_content"].strip(), ""]
    lines += ["## Aprobaciones", "", "| Departamento | Aprobó | Fecha |", "|---|---|---|"]
    for d in ordered:
        lines.append(f"| {DEPARTMENTS[d].name} | {sections[d].get('approver')} | {str(sections[d].get('approved_at'))[:10]} |")
    if ceo and ceo.get("required"):
        lines.append(f"| Dirección (CEO) | {ceo.get('approver')} | {str(ceo.get('approved_at'))[:10]} |")
    pending = [p for d in ordered for p in (sections[d].get("pending_items") or [])]
    if pending:
        lines += ["", "## Pendiente de definir", ""] + [f"- {p}" for p in dict.fromkeys(pending)]
    return {"ticket_id": ticket_id, "content": "\n".join(lines).strip() + "\n", "total_estimated_value": value,
            "generated_at": now.isoformat(), "compliance": {"pass": True, "checked_rules": check["checked_rules"]},
            "sections": [{"department_id": d, "owner": DEPARTMENTS[d].owner, "approver": sections[d].get("approver"),
                          "approved_at": str(sections[d].get("approved_at")), "iterations": sections[d].get("iterations"),
                          "approval_rounds": sections[d].get("approval_round")} for d in ordered]}
