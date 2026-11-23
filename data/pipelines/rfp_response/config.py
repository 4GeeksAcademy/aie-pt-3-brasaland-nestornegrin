"""Constantes de la Parte 2 (generación y evaluación). Todo lo que sale del company-BRIEFING (§5) está aquí con su referencia."""
from __future__ import annotations

import os

SCHEMA_VERSION = 1

# Estados del ticket de ESTA parte (BRIEFING §2.3). Los de la Parte 3 (esperando_aprobación, terminado) NO se usan aquí.
STATUS_GENERATING = "generando_borrador"
STATUS_EVALUATING = "en_evaluación"
STATUS_NEEDS_REVIEW = "needs_human_review"
PART2_STATUSES = (STATUS_GENERATING, STATUS_EVALUATING, STATUS_NEEDS_REVIEW)

# Estado de cada SECCIÓN (un departamento) durante el ciclo generador-evaluador.
SECTION_PENDING, SECTION_GENERATING, SECTION_EVALUATING, SECTION_PASSED, SECTION_NEEDS_REVIEW, SECTION_ERROR = (
    "pendiente", "generando", "en_evaluacion", "paso", "needs_human_review", "error")
SECTION_FINAL = (SECTION_PASSED, SECTION_NEEDS_REVIEW)

DEFAULT_MAX_ITERATIONS = 3  # generaciones por sección (1 inicial + 2 reintentos con feedback)


def max_iterations() -> int:
    try:
        return max(1, int(os.environ.get("RFP_MAX_ITERATIONS", DEFAULT_MAX_ITERATIONS)))
    except ValueError:
        return DEFAULT_MAX_ITERATIONS


# ---- BRIEFING §5: lineamientos contra los que se evalúa el cumplimiento --------------------------------------------
BRAND_PILLARS = ("calidad consistente", "experiencia cálida", "velocidad de servicio")  # §5: «al menos una vez»
OFFER_VALIDITY_DAYS = 30  # §5: validez de la oferta (30 días desde su emisión)
MIN_SETUP_BUSINESS_DAYS = 10  # §5: nada de montaje/entrega por debajo de 10 días hábiles (trigger `setup-sla-breach`, §7)

# El BRIEFING dice «ninguna propuesta puede mencionar nombres de competidores» pero NO entrega la lista. Supuesto documentado:
# cadenas colombianas de comida casual comparables; se sobrescribe con RFP_COMPETITORS="a,b,c" (Marketing debe validarla).
DEFAULT_COMPETITORS = ("El Corral", "Crepes & Waffles", "Frisby", "Kokoriko", "Presto", "Archies", "Wok", "Sandwich Qbano",
                       "McDonald's", "Burger King", "KFC", "Subway", "Starbucks", "Juan Valdez", "Rappi")


def competitors() -> tuple[str, ...]:
    raw = os.environ.get("RFP_COMPETITORS")
    return tuple(x.strip() for x in raw.split(",") if x.strip()) if raw else DEFAULT_COMPETITORS


def usd_cop_rate() -> float | None:
    """TRM (COP por USD) que usa el generador para expresar los precios en ambas monedas (§5). NO se inventa: si no está
    configurada (RFP_USD_COP_RATE), el generador no escribe montos y los marca como pendientes."""
    try:
        rate = float(os.environ.get("RFP_USD_COP_RATE", ""))
    except ValueError:
        return None
    return rate if rate > 0 else None


# ---- Legibilidad ---------------------------------------------------------------------------------------------------
MIN_WORDS, MAX_WORDS = 60, 400  # una sección de propuesta: ni una línea suelta ni un tratado
MAX_AVG_WORDS_PER_SENTENCE = 30
MIN_HUERTA_ES = 45  # Fernández-Huerta: <30 muy difícil, 30–50 difícil, 50–60 algo difícil, 60–70 normal
MAX_FK_GRADE_EN = 14.0
