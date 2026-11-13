"""Lo MÍNIMO que un humano necesita ver para decidir con confianza sin releer el documento (pregunta de diseño 2).

Para un departamento: su borrador, si es provisional y por qué, el resultado de los tres evaluadores en una línea cada uno, los
aspectos clave que debía cubrir, lo que quedó pendiente, los conflictos que lo afectan, qué cambió desde la ronda anterior y
quién puede decidir. Para la CEO: valor, estado de cada departamento y conflictos abiertos."""
from __future__ import annotations

from data.pipelines.rfp_intake.departments import DEPARTMENTS

from . import config


def _verdict(ev: dict | None) -> dict:
    if not ev:
        return {}
    return {"legibilidad": ev["readability"]["pass"], "pertinencia": ev["relevance"]["pass"], "cumplimiento": ev["compliance"]["pass"],
            "reglas_incumplidas": ev["compliance"].get("rule_ids", []), "aspectos_sin_cubrir": ev["relevance"].get("missing_aspects", []),
            "feedback": "" if ev.get("overall_pass") else ev.get("feedback_for_generator", "")}


def deal_context(handoff: dict, ceo: dict | None) -> dict:
    m = (handoff or {}).get("metadata", {})
    return {"cliente": m.get("client_name"), "ubicacion": m.get("location"), "servicio": m.get("service_type"), "alcance": m.get("scope"),
            "fecha_limite": m.get("deadline"), "presupuesto": m.get("budget_range"),
            "valor_anual_estimado_usd": (ceo or {}).get("estimated_annual_value_usd"),
            "requiere_aprobacion_ceo": bool((ceo or {}).get("required"))}


def department_packet(ticket_id: int, department_id: str, round_: int, section: dict, handoff: dict, ceo: dict | None, conflicts: list[dict]) -> dict:
    history = section.get("approval_history") or []
    last = history[-1] if history else None
    return {"kind": "department_approval", "ticket_id": ticket_id, "department_id": department_id,
            "department": DEPARTMENTS[department_id].name, "owner": DEPARTMENTS[department_id].owner, "round": round_,
            "max_rounds": config.max_rounds(),
            "may_decide": sorted({DEPARTMENTS[department_id].owner} | ({config.ARBITER_NAME} if section.get("escalated") else set())),
            "actions": list(config.ACTIONS), "context": deal_context(handoff, ceo),
            "draft": section.get("draft_content") or "", "provisional": bool(section.get("needs_human_review")),
            "provisional_reason": ("Agotó las iteraciones del evaluador sin pasar todas las reglas: revisa el feedback." if section.get("needs_human_review") else None),
            "evaluation": _verdict(section.get("evaluation_results")), "key_aspects": [a["aspect"] for a in section.get("key_aspects", [])],
            "pending_items": section.get("pending_items") or [], "open_questions": section.get("open_questions") or [],
            "conflicts": [{"trigger_id": c["trigger_id"], "arbiter": c["arbiter"], "resolution": c["resolution"]}
                          for c in conflicts if department_id in c["departments"] and c["status"] == "abierto"],
            "previous_round": last}


def ceo_packet(ticket_id: int, round_: int, sections: dict[str, dict], handoff: dict, ceo: dict, conflicts: list[dict]) -> dict:
    return {"kind": "ceo_approval", "ticket_id": ticket_id, "department_id": config.CEO_ID, "department": "Dirección (CEO)",
            "owner": config.CEO_NAME, "round": round_, "may_decide": [config.CEO_NAME], "actions": list(config.ACTIONS),
            "context": deal_context(handoff, ceo), "threshold_usd": config.CEO_APPROVAL_THRESHOLD_USD,
            "sections": [{"department_id": d, "owner": DEPARTMENTS[d].owner, "approval_status": s.get("approval_status"),
                          "approver": s.get("approver"), "provisional": bool(s.get("needs_human_review")),
                          "excerpt": (s.get("draft_content") or "")[:240]} for d, s in sections.items()],
            "conflicts": [{"trigger_id": c["trigger_id"], "status": c["status"]} for c in conflicts],
            "previous_round": (ceo.get("history") or [None])[-1]}
