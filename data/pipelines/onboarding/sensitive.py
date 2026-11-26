"""Datos sensibles (BRIEFING): documento de identidad, datos bancarios para nómina, salario y condiciones económicas del contrato.

El sistema trabaja SOLO con el estado de cada trámite ("contrato recibido"), nunca con su contenido. Esta barrera es la segunda línea
de defensa: aunque alguien escriba un dato así en una duda o en un comentario, se sustituye por una marca ANTES de guardarlo, de
registrarlo o de devolverlo. La primera línea es el diseño: ningún modelo de entrada tiene un campo para esos datos."""
from __future__ import annotations

import re

MARK = "[dato sensible omitido]"

_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("documento_identidad", re.compile(r"(?i)\b(c[eé]dula|c\.?\s?c\.?|c[eé]dula de extranjer[ií]a|pasaporte|passport|ssn|social security|documento|dni|nie|nit)\b[^\n\d]{0,25}[A-Z]{0,2}[\d][\d .\-]{5,}")),
    ("documento_identidad", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),                       # SSN de EE. UU.
    ("documento_identidad", re.compile(r"\b\d{1,3}(?:\.\d{3}){2,3}\b")),                  # cédula con puntos: 1.037.612.345
    ("documento_identidad", re.compile(r"\b[A-Z]{1,2}\d{6,9}\b")),                       # pasaporte: AB1234567
    ("datos_bancarios", re.compile(r"(?i)\b(cuenta|iban|swift|routing|aba|clabe|tarjeta|card|n[uú]mero de cuenta|account)\b[^\n\d]{0,25}[A-Z]{0,2}\d[\d .\-]{5,}")),
    ("datos_bancarios", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")),                 # IBAN
    ("datos_bancarios", re.compile(r"\b(?:\d[ -]?){13,19}\b")),                           # número de tarjeta / cuenta largo
    ("salario", re.compile(r"(?i)\b(salario|sueldo|salary|compensaci[oó]n|bonificaci[oó]n|bono|honorarios|pago mensual|retribuci[oó]n|"
                           r"paga|ingresos?)\b[^\n\d]{0,25}[$€]?\s?\d[\d.,]*(?:\s?(?:k|mil|millones|cop|usd|dólares|dolares|pesos))?")),
    ("salario", re.compile(r"(?i)\b(?:me\s+(?:van\s+a\s+)?pag(?:an|ar[aá]n)|gano|cobro|ganar[eé])\b[^\n\d]{0,25}[$€]?\s?\d[\d.,]*(?:\s?(?:k|mil|millones|cop|usd|dólares|dolares|pesos))?")),
)

_PATTERNS += (
    ("salario", re.compile(r"(?i)\b(?:i\s+)?(?:earn|earns|make|makes|am paid|get paid|paid)\b[^\n\d]{0,25}[$€]?\s?\d[\d.,]*(?:\s?(?:k|usd|dollars))?")),
    ("salario", re.compile(r"[$€]\s?\d[\d.,]*(?:\s?(?:k|usd|cop))?")),                # cualquier importe con símbolo de moneda
)

# Preguntas SOBRE los propios datos económicos o de identidad: el agente no los tiene ni los gestiona; las deriva a Personas.
_OWN_DATA_QUESTION = re.compile(
    r"(?i)\b(mi|cu[aá]nto|cu[aá]l)\b.*\b(salario|sueldo|pago|n[oó]mina|cuenta bancaria|c[eé]dula|pasaporte|condiciones econ[oó]micas|bono|bonificaci[oó]n)\b|"
    r"\b(salario|sueldo|n[oó]mina|cuenta bancaria|condiciones econ[oó]micas)\b.*\b(mi|m[ií]o|m[ií]a)\b")


def redact(text: str | None) -> tuple[str, list[str]]:
    """Devuelve (texto sin datos sensibles, tipos detectados)."""
    if not text:
        return "", []
    found: list[str] = []
    clean = text
    for kind, pattern in _PATTERNS:
        clean, count = pattern.subn(MARK, clean)
        if count and kind not in found:
            found.append(kind)
    return clean, found


def contains_sensitive(text: str | None) -> bool:
    return bool(redact(text)[1])


def asks_about_own_sensitive_data(question: str) -> bool:
    return bool(_OWN_DATA_QUESTION.search(question or ""))
