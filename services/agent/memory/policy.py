"""Política de memoria de Brasaland: qué se puede recordar y qué NUNCA entra (BRIEFING del Hito 8, Parte 1).

El prompt le pide al modelo que respete la política, pero el prompt no es una barrera: esta capa es DETERMINISTA y se
ejecuta sobre lo que el modelo propone (y sobre la edición que escribe el usuario) antes de guardar nada. Si algo no
pasa, la propuesta se descarta y no llega a mostrarse.

NUNCA entra en memoria (BRIEFING):
  1. Datos personales de clientes de Brasa Points más allá de lo operativo (viven en el CRM).
  2. Cifras de nómina o compensación individual del personal.
  3. Datos de una conversación puntual sin patrón repetible (una queja de un cliente un solo día).

Además, defensa contra «envenenamiento»: el hecho debe salir del mensaje del usuario (anclaje léxico y numérico), no
puede contener instrucciones dirigidas al agente, enlaces ni marcado, y tiene un tamaño acotado.
"""
from __future__ import annotations

import re
import unicodedata

from .models import CATEGORIES, MemoryProposal

MIN_FACT_CHARS = 12
MAX_FACT_CHARS = 300
MAX_LOCATION_CHARS = 60
MAX_TOPIC_CHARS = 60
GROUNDING_RATIO = 0.6  # fracción mínima de palabras significativas del hecho que deben estar en el mensaje del usuario

CATEGORY_LABELS = {
    "es": {"horarios": "horarios", "proveedores": "proveedores", "incidentes_conocidos": "incidentes conocidos",
           "preferencias_comunicacion": "preferencias de comunicación",
           "excepciones_procedimiento": "excepciones a un procedimiento"},
    "en": {"horarios": "hours", "proveedores": "suppliers", "incidentes_conocidos": "known incidents",
           "preferencias_comunicacion": "communication preferences",
           "excepciones_procedimiento": "procedure exceptions"},
}


def normalize(text: str) -> str:
    """Minúsculas y sin tildes, para comparar sin que «miércoles» y «miercoles» difieran."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", normalize(text)).strip("_")


# --- Lo que NUNCA debe entrar -------------------------------------------------------------------------------------
_PAYROLL = re.compile(
    r"\b(salari\w*|sueldo\w*|nomina\w*|compensacion\w*|bonificacion\w*|bonos?|payroll|salary|salaries|wages?|"
    r"paychecks?|pay raise|aumento de (sueldo|salario)|liquidacion)\b"
    r"|\b(gana|ganan|cobra|cobran|paga|pagan|earns?|makes?)\b[^.]{0,40}(\$|\bcop\b|\busd\b|\d{3,})")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?:\+?\d[\s().-]?){7,}")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_ID_DOCUMENT = re.compile(r"\b(cedula|cc|nit|pasaporte|passport|ssn|documento|dni)\b\s*[:#]?\s*\d")
_CUSTOMER = re.compile(r"\b(clientes?|customers?|socios?|miembros?|members?|brasa points)\b")
_CUSTOMER_DATA = re.compile(
    r"\b(puntos|points|nivel|tier|saldo|balance|correo|email|telefono|phone|direccion|address|cumpleanos|birthday|"
    r"alergi\w*|allerg\w*|nombre|name|queja|complaint|reclamo)\b")

# --- Defensa contra envenenamiento / inyección --------------------------------------------------------------------
_INSTRUCTION = re.compile(
    r"\b(ignor[ae]\w*|olvida\w*|a partir de ahora|de ahora en adelante|siempre (responde|di|obedece|haz)|"
    r"nunca (digas|respondas|menciones)|system prompt|prompt del sistema|instrucciones (anteriores|previas|del sistema)|"
    r"ignore (all|previous|the|your)|disregard|you (must|should) always|from now on|act as|actua como|eres un|"
    r"jailbreak|developer mode|modo desarrollador)\b")
_MARKUP = re.compile(r"(```|</?\w+>|https?://|www\.|\{\{|\}\}|\[\[)")

_STOPWORDS = frozenset(
    "para como pero esta este esto esos esas cuando donde desde hasta sobre entre porque tambien tiene tienen "
    "from that this with have they their there which will would been were when what also into than then them".split())


def forbidden_reasons(text: str) -> list[str]:
    """Motivos (códigos estables) por los que `text` contiene algo que el BRIEFING prohíbe guardar."""
    clean = normalize(text)
    reasons: list[str] = []
    if _PAYROLL.search(clean):
        reasons.append("nomina_o_compensacion")
    if _EMAIL.search(text) or _PHONE.search(_DATE.sub(" ", text)) or _ID_DOCUMENT.search(clean):
        reasons.append("dato_personal_identificable")
    if _CUSTOMER.search(clean) and _CUSTOMER_DATA.search(clean):
        reasons.append("datos_de_clientes_brasa_points")
    return reasons


def _significant_tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"\w+", normalize(text)) if len(token) > 3 and token not in _STOPWORDS]


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+", normalize(text)))


def grounded_in(fact: str, user_message: str) -> bool:
    """¿El hecho sale del mensaje del usuario? Todos sus números deben aparecer en el mensaje (horas, fechas) y la
    mayoría de sus palabras significativas también (comparando por prefijo de 5 letras: entrega/entregan)."""
    if not _numbers(fact) <= _numbers(user_message):
        return False
    message_prefixes = {token[:5] for token in _significant_tokens(user_message)}
    tokens = _significant_tokens(fact)
    if not tokens:
        return False
    hits = sum(1 for token in tokens if token[:5] in message_prefixes)
    return hits / len(tokens) >= GROUNDING_RATIO


def fact_issues(fact: str, user_message: str) -> list[str]:
    """Problemas del texto que se guardaría (vacío = válido). Se aplica a la propuesta del modelo y a la edición del usuario."""
    if not isinstance(fact, str):
        return ["hecho_invalido"]
    issues: list[str] = []
    stripped = fact.strip()
    if not MIN_FACT_CHARS <= len(stripped) <= MAX_FACT_CHARS:
        issues.append("longitud_fuera_de_rango")
    if "\n" in stripped:
        issues.append("no_es_una_sola_frase")
    clean = normalize(stripped)
    if _INSTRUCTION.search(clean) or _MARKUP.search(stripped):
        issues.append("instruccion_o_marcado")
    issues.extend(forbidden_reasons(stripped))
    if not grounded_in(stripped, user_message):
        issues.append("no_sale_del_mensaje_del_usuario")
    return issues


def validate_proposal(raw: dict | None, user_message: str) -> tuple[MemoryProposal | None, list[str]]:
    """Convierte `propuesta_memoria` (lo que devolvió el modelo) en una `MemoryProposal` o explica por qué no vale.

    Devuelve `(None, [])` cuando el modelo dijo que no hay nada que recordar (el caso normal) y `(None, motivos)`
    cuando propuso algo que la política rechaza."""
    if not isinstance(raw, dict) or not raw.get("aplica"):
        return None, []
    issues: list[str] = []
    category = str(raw.get("categoria") or "").strip()
    if category not in CATEGORIES:
        issues.append("categoria_no_permitida")
    if raw.get("repetible") is not True:
        issues.append("sin_patron_repetible")
    location = str(raw.get("ubicacion") or "").strip()
    if not location or len(location) > MAX_LOCATION_CHARS:
        issues.append("ubicacion_invalida")
    topic = slug(str(raw.get("tema") or ""))[:MAX_TOPIC_CHARS]
    if not topic:
        issues.append("tema_invalido")
    fact = str(raw.get("hecho") or "").strip()
    issues.extend(fact_issues(fact, user_message))
    if _INSTRUCTION.search(normalize(location + " " + topic)) or _MARKUP.search(location):
        issues.append("instruccion_o_marcado")
    if issues:
        return None, sorted(set(issues))
    language = "en" if str(raw.get("idioma") or "").lower().startswith("en") else "es"
    return MemoryProposal(location=location, category=category, topic=topic, fact=fact,
                          rationale=str(raw.get("motivo") or "").strip()[:200], language=language), []
