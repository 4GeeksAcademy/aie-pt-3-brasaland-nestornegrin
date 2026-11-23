"""Arbitraje de la Parte 3: nodo determinista, sin LLM. Detecta los triggers del BRIEFING §7 sobre ESTADO ESTRUCTURADO (secciones,
cifras, aprobaciones) y los resuelve con el árbitro fijo y la regla de resolución del BRIEFING. Los agentes pueden señalar un
conflicto; nunca lo resuelven por consenso.

| trigger             | se detecta en…                                                        | árbitro fijo                         | resolución                                        |
|---------------------|-----------------------------------------------------------------------|--------------------------------------|---------------------------------------------------|
| setup-sla-breach    | el texto de CADA sección (parser de plazos de la Parte 2)             | Felipe Guerrero; Camila si otro depto | forzar request_changes hasta ≥ 10 días hábiles    |
| cost-vs-feasibility | cifras estructuradas: costo de procurement > precio de operaciones    | Camila Ospina (dueña del ticket)      | subir precio o reducir alcance (request_changes)  |
| ceo-threshold       | valor anual estimado > 50.000 USD y aprobación de la CEO pendiente    | Mariana Restrepo (CEO)                | bloquear la síntesis hasta su approve             |
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

from data.pipelines.rfp_response.rules import check_setup_times

from . import config

BRIEFING_REF = "BRIEFING §7"
FELIPE = config.owner_of("operaciones")
UNITS = {"cubierto": "cubierto", "cover": "cubierto", "plato": "cubierto", "evento": "evento", "event": "evento"}


def _token_set(key: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", key.lower()).encode("ascii", "ignore").decode()
    return set(re.split(r"[^a-z0-9]+", folded))


def to_float(raw: str) -> float | None:
    text = re.sub(r"[^\d.,]", "", str(raw))
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".") if re.fullmatch(r"\d+,\d{1,2}", text) else text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def unit_economics(figures: dict, kind: str) -> dict[str, float]:
    """Cifras estructuradas en USD por unidad. `kind`: «precio» (operaciones) o «costo» (procurement).
    Las llaves se reconocen por palabras: precio_por_cubierto_usd, price_per_event_usd, costo_insumos_por_cubierto_usd…"""
    words = ("precio", "price") if kind == "precio" else ("costo", "cost")
    out: dict[str, float] = {}
    for key, value in (figures or {}).items():
        tokens = _token_set(key)
        unit = next((UNITS[t] for t in tokens if t in UNITS), None)
        number = to_float(value)
        if unit and number is not None and "usd" in tokens and tokens & set(words):
            out[unit] = number
    return out


def _conflict(trigger: str, arbiter: str, departments: list[str], evidence: list[dict], resolution: str, *, blocking: bool = True,
              forced: dict[str, str] | None = None) -> dict:
    return {"trigger_id": trigger, "arbiter": arbiter, "briefing_ref": BRIEFING_REF, "departments": sorted(departments),
            "evidence": evidence, "resolution": resolution, "blocking": blocking, "forced_changes": forced or {},
            "key": f"{trigger}:{','.join(sorted(departments))}"}


def detect(sections: dict[str, dict], ceo: dict | None, overridden: set[str] | None = None) -> list[dict]:
    """Conflictos presentes AHORA en el estado estructurado. Es una función pura: mismo estado → mismos conflictos."""
    overridden, found = overridden or set(), []
    # 1) setup-sla-breach — cualquier sección que prometa montaje/entrega bajo 10 días hábiles (BRIEFING §5/§7). No se puede anular.
    offenders = {d: check_setup_times(s.get("draft_content") or "") for d, s in sections.items()}
    offenders = {d: v for d, v in offenders.items() if v}
    if offenders:
        arbiter = FELIPE if "operaciones" in offenders else config.ARBITER_NAME
        forced = {d: (f"[ARBITRAJE · {config.TRIGGER_SLA} · {BRIEFING_REF} · {'Felipe Guerrero (operaciones) rechaza' if d == 'operaciones' else 'Camila Ospina escala'}] "
                      f"{v[0]['message']} Frase: «{v[0]['excerpt']}». Ajusta el plazo a ≥ {config.part2.MIN_SETUP_BUSINESS_DAYS} días hábiles.")
                  for d, v in offenders.items()}
        found.append(_conflict(config.TRIGGER_SLA, arbiter, list(offenders),
                               [{"department_id": d, "excerpt": v[0]["excerpt"], "message": v[0]["message"],
                                 "decided_by": FELIPE if d == "operaciones" else config.ARBITER_NAME} for d, v in offenders.items()],
                               "Forzar request_changes hasta ≥ 10 días hábiles en todas partes.", forced=forced))
    # 2) cost-vs-feasibility — el costo de procurement no soporta el precio implícito de operaciones (misma unidad, USD).
    price = unit_economics((sections.get("operaciones") or {}).get("figures", {}), "precio")
    cost = unit_economics((sections.get("procurement") or {}).get("figures", {}), "costo")
    for unit in sorted(set(price) & set(cost)):
        if cost[unit] > price[unit]:
            c = _conflict(config.TRIGGER_COST, config.ARBITER_NAME, ["operaciones", "procurement"],
                          [{"unit": unit, "price_usd": price[unit], "cost_usd": cost[unit]}],
                          "Subir precio o reducir alcance; forzar request_changes en las secciones desalineadas.")
            msg = (f"[ARBITRAJE · {config.TRIGGER_COST} · {BRIEFING_REF} · Camila Ospina] El costo de insumos por {unit} "
                   f"({cost[unit]:,.2f} USD, procurement) no soporta el precio por {unit} de operaciones ({price[unit]:,.2f} USD). "
                   "Sube el precio o reduce el alcance.")
            c["forced_changes"] = {"operaciones": msg, "procurement": msg}
            if c["key"] not in overridden:
                found.append(c)
            break
    # 3) ceo-threshold — valor anual > 50.000 USD y la CEO todavía no aprobó: bloquea la síntesis (no fuerza cambios).
    if ceo and ceo.get("required") and ceo.get("status") != config.APPROVAL_APPROVED:
        found.append(_conflict(config.TRIGGER_CEO, config.CEO_NAME, [config.CEO_ID],
                               [{"estimated_annual_value_usd": ceo.get("estimated_annual_value_usd"), "threshold_usd": config.CEO_APPROVAL_THRESHOLD_USD}],
                               "Bloquear la síntesis final hasta el approve de la CEO; si rechaza, la sección de marketing vuelve a cambios.",
                               blocking=True))
    return found


def merge_log(log: list[dict], detected: list[dict], now: datetime | None = None) -> tuple[list[dict], list[dict]]:
    """Actualiza el registro de conflictos del ticket: abre los nuevos y cierra los que ya no existen. Devuelve (log, nuevos)."""
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    present = {c["key"] for c in detected}
    out = [dict(e) for e in log]
    for entry in out:
        if entry["status"] == "abierto" and entry["key"] not in present:
            entry.update(status="resuelto", resolved_at=stamp)
    opened = {e["key"] for e in out if e["status"] == "abierto"}
    new = [c for c in detected if c["key"] not in opened]
    for c in new:
        out.append({**{k: v for k, v in c.items() if k != "forced_changes"}, "status": "abierto", "detected_at": stamp, "resolved_at": None})
    return out, new
