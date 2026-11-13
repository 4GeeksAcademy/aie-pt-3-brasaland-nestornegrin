"""Evaluadores DETERMINISTAS (legibilidad y cumplimiento). El cumplimiento no es «un juicio de estilo libre»: cada regla sale
del company-BRIEFING §5 y se verifica en código, con la cita exacta del texto que la incumple.

Reglas (rule_id → BRIEFING):
  price-dual-currency   §5 «Todo precio debe expresarse en COP y en USD»
  brand-pillars         §5 «Toda propuesta debe mencionar, al menos una vez, los tres pilares de la marca»
  setup-sla-breach      §5 «Ninguna sección puede prometer tiempos de montaje/entrega menores a 10 días hábiles» (trigger §7)
  no-competitors        §5 «Ninguna propuesta puede mencionar nombres de competidores»
  offer-validity-30d    §5 «Toda propuesta debe incluir un período de validez de la oferta (30 días desde su emisión)»
  no-invented-figures   §2.3 «nunca inventes números que no estén en el documento»
«Toda propuesta» es una regla de la PROPUESTA completa: la lleva la sección del dueño del ticket (marketing), que es la que
redacta los términos comerciales; en las demás secciones solo se prohíbe contradecirla (p. ej. otra validez distinta).
"""
from __future__ import annotations

import math
import re

from data.pipelines.rfp_intake.agents import _norm, numbers_in
from data.pipelines.rfp_intake.departments import OWNER_DEPARTMENT
from data.pipelines.rfp_intake.readability_metrics import measure

from . import config

BRIEFING_REF = {"price-dual-currency": "§5", "brand-pillars": "§5", "setup-sla-breach": "§5 / §7", "no-competitors": "§5",
                "offer-validity-30d": "§5", "no-invented-figures": "§2.3"}
ALL_RULES = tuple(BRIEFING_REF)

_NUMBER_WORDS = {"un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
                 "diez": 10, "once": 11, "doce": 12, "quince": 15, "veinte": 20, "treinta": 30}
_NUM = r"(?:\d+|" + "|".join(_NUMBER_WORDS) + r")"
_UNIT = r"(?:dias?|semanas?|horas?|meses|mes)"


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip(" -*•\t") for p in parts if p and p.strip(" -*•\t")]


def _strip_enumerators(text: str) -> str:
    return re.sub(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+", "", text)


# --------------------------------------------------------------------------------------------- price-dual-currency
_USD = re.compile(r"(?:\bUSD\b|\bUS\s?\$|\bdolares?\b|\bdólares?\b)", re.I)
_COP = re.compile(r"(?:\bCOP\b|\bpesos\b)", re.I)
_BARE_DOLLAR = re.compile(r"\$\s?\d")
_AMOUNT = re.compile(r"\d[\d.,]*\d|\d")


def check_prices(text: str) -> list[dict]:
    out = []
    for s in sentences(text):
        if not _AMOUNT.search(s):
            continue
        usd, cop, bare = bool(_USD.search(s)), bool(_COP.search(s)), bool(_BARE_DOLLAR.search(s))
        if usd and cop:
            continue
        if usd:
            msg = "Hay un monto en USD sin su equivalente en COP en la misma frase."
        elif cop:
            msg = "Hay un monto en COP sin su equivalente en USD en la misma frase."
        elif bare:
            msg = "Monto con «$» sin moneda: todo precio debe expresarse en COP y en USD."
        else:
            continue
        out.append({"rule_id": "price-dual-currency", "message": msg, "excerpt": s})
    return out


# --------------------------------------------------------------------------------------------- setup-sla-breach
_SETUP_WORDS = re.compile(r"(montaje|instalaci|entrega|puesta en (?:marcha|operacion|funcionamiento)|implementaci|arranque|despliegue|"
                          r"inicio de (?:operacion|servicio)|listo en|habilit|operando en|lanzamiento)")
_DURATION = re.compile(rf"(?:(?:entre\s+)?({_NUM})\s*(?:a|-|–|y)\s*)?({_NUM})\s+({_UNIT})(?:\s+(habil(?:es)?))?(?:\s+(calendario))?")
_IMMEDIATE = re.compile(r"(inmediat|mismo dia|al instante|de un dia para otro|sin demora|de inmediato)")


def _to_int(token: str) -> int:
    return int(token) if token.isdigit() else _NUMBER_WORDS[token]


def business_days(amount: int, unit: str, calendar: bool) -> int:
    if unit.startswith("semana"):
        return amount * 5
    if unit.startswith("hora"):
        return math.ceil(amount / 8)
    if unit.startswith("mes"):
        return amount * 21
    return amount * 5 // 7 if calendar else amount  # «días» sin más se leen como hábiles; «calendario» se convierte


def check_setup_times(text: str) -> list[dict]:
    out = []
    for s in sentences(text):
        n = _norm(s)
        if not _SETUP_WORDS.search(n):
            continue
        shortest = None
        for m in _DURATION.finditer(n):
            low, high, unit, _, calendar = m.groups()
            values = [business_days(_to_int(x), unit, bool(calendar)) for x in (low, high) if x]
            shortest = min([v for v in values] + ([shortest] if shortest is not None else []))
        if shortest is not None and shortest < config.MIN_SETUP_BUSINESS_DAYS:
            out.append({"rule_id": "setup-sla-breach", "excerpt": s,
                        "message": f"Promete montaje/entrega en ≈{shortest} días hábiles; el mínimo permitido es {config.MIN_SETUP_BUSINESS_DAYS}."})
        elif shortest is None and _IMMEDIATE.search(n):
            out.append({"rule_id": "setup-sla-breach", "excerpt": s,
                        "message": f"Promete montaje/entrega inmediata; el mínimo permitido es {config.MIN_SETUP_BUSINESS_DAYS} días hábiles."})
    return out


# --------------------------------------------------------------------------------------------- resto de reglas
def check_competitors(text: str) -> list[dict]:
    out, n = [], _norm(text)
    for name in config.competitors():
        if re.search(rf"(?<![a-z0-9]){re.escape(_norm(name))}(?![a-z0-9])", n):
            line = next((s for s in sentences(text) if _norm(name) in _norm(s)), name)
            out.append({"rule_id": "no-competitors", "message": f"Menciona un competidor ({name}).", "excerpt": line})
    return out


def check_pillars(text: str, department_id: str) -> list[dict]:
    if department_id != OWNER_DEPARTMENT:
        return []
    n = _norm(text)
    missing = [p for p in config.BRAND_PILLARS if _norm(p) not in n]
    return [{"rule_id": "brand-pillars", "excerpt": "",
             "message": "Faltan pilares de marca: " + ", ".join(missing) + ". Deben aparecer los tres, con esa redacción."}] if missing else []


_VALIDITY = re.compile(rf"(?:validez|vigencia|vigente|valida)[^.\n]{{0,80}}?(\d+)\s+dias")


def check_validity(text: str, department_id: str) -> list[dict]:
    n = _norm(text)
    out = []
    for m in _VALIDITY.finditer(n):
        if int(m.group(1)) != config.OFFER_VALIDITY_DAYS:
            line = next((s for s in sentences(text) if m.group(0)[:20] in _norm(s)), m.group(0))
            out.append({"rule_id": "offer-validity-30d", "excerpt": line,
                        "message": f"La validez de la oferta es de {config.OFFER_VALIDITY_DAYS} días, no {m.group(1)}."})
    if department_id == OWNER_DEPARTMENT and not re.search(rf"(validez|vigencia)[^.\n]{{0,80}}?{config.OFFER_VALIDITY_DAYS}\s+dias", n):
        out.append({"rule_id": "offer-validity-30d", "excerpt": "",
                    "message": f"Falta el período de validez de la oferta: {config.OFFER_VALIDITY_DAYS} días desde su emisión."})
    return out


_ALWAYS_OK = {str(config.OFFER_VALIDITY_DAYS), str(config.MIN_SETUP_BUSINESS_DAYS)}


def check_figures(text: str, allowed_numbers: set[str]) -> list[dict]:
    out = []
    for s in sentences(text):
        bad = sorted(n for n in numbers_in(_strip_enumerators(s)) if n not in allowed_numbers and n not in _ALWAYS_OK)
        if bad:
            out.append({"rule_id": "no-invented-figures", "excerpt": s,
                        "message": f"Cifra(s) que no están en la RFP ni en el análisis de la Parte 1: {', '.join(bad)}. "
                                   "Quítalas o escribe «pendiente de confirmar»."})
    return out


def evaluate_compliance(text: str, department_id: str, allowed_numbers: set[str]) -> dict:
    violations = (check_prices(text) + check_pillars(text, department_id) + check_setup_times(text) + check_competitors(text)
                  + check_validity(text, department_id) + check_figures(text, allowed_numbers))
    specific = {v["excerpt"] for v in violations if v["rule_id"] in ("offer-validity-30d", "setup-sla-breach") and v["excerpt"]}
    violations = [v for v in violations if not (v["rule_id"] == "no-invented-figures" and v["excerpt"] in specific)]  # la regla específica ya lo explica
    for v in violations:
        v["briefing_ref"] = BRIEFING_REF[v["rule_id"]]
    return {"pass": not violations, "rule_ids": list(dict.fromkeys(v["rule_id"] for v in violations)), "violations": violations,
            "checked_rules": list(ALL_RULES)}


# --------------------------------------------------------------------------------------------- legibilidad
def evaluate_readability(text: str) -> dict:
    m = measure(text)
    problems, language = [], m["language"]
    long_sentences = sorted(sentences(text), key=lambda s: -len(s.split()))[:3]
    if m["word_count"] < config.MIN_WORDS:
        problems.append(f"Muy corta ({m['word_count']} palabras; mínimo {config.MIN_WORDS}): desarrolla los puntos que le tocan al departamento.")
    if m["word_count"] > config.MAX_WORDS:
        problems.append(f"Muy larga ({m['word_count']} palabras; máximo {config.MAX_WORDS}): resume.")
    if m["avg_words_per_sentence"] > config.MAX_AVG_WORDS_PER_SENTENCE:
        problems.append(f"Las oraciones promedian {m['avg_words_per_sentence']} palabras (máximo {config.MAX_AVG_WORDS_PER_SENTENCE}): "
                        "divide las más largas.")
    if language == "es" and m["fernandez_huerta"] is not None:
        score = m["fernandez_huerta"]
        if score < config.MIN_HUERTA_ES:
            problems.append(f"Índice Fernández-Huerta {score} (mínimo {config.MIN_HUERTA_ES}): usa frases más cortas y palabras más simples.")
    else:
        grade = m["flesch_kincaid_grade"]
        score = m["flesch_reading_ease"] if m["flesch_reading_ease"] is not None else 0.0
        if grade is not None and grade > config.MAX_FK_GRADE_EN:
            problems.append(f"Nivel Flesch-Kincaid {grade} (máximo {config.MAX_FK_GRADE_EN}): simplifica.")
    return {"pass": not problems, "score": score,
            "details": {"metrics": {k: m[k] for k in ("language", "word_count", "sentence_count", "avg_words_per_sentence",
                                                     "fernandez_huerta", "flesch_kincaid_grade", "flesch_reading_ease")},
                        "problems": problems, "longest_sentences": long_sentences if problems else []}}
