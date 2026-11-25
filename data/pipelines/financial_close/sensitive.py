"""Datos sensibles (BRIEFING): salarios individuales y datos bancarios de proveedores. La nómina entra SOLO agregada por país (el libro no
tiene líneas por persona). Defensa en capas: (1) el modelo de datos no tiene campo para ellos; (2) la ingesta marca como DUDOSO y excluye
cualquier línea de nómina por persona; (3) `redact()` sustituye cuentas bancarias y salarios individuales ANTES de guardar, registrar,
enviar o devolver nada."""
from __future__ import annotations

import re

MARK = "[dato sensible omitido]"

_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("datos_bancarios", re.compile(r"(?i)\b(cuenta|account|iban|swift|routing|aba|clabe|banco|bank|titular|holder)\b[^\n;|]{0,40}?\d[\d .\-]{5,}\d")),
    ("datos_bancarios", re.compile(r"\b\d{3,4}[-\s]\d{5,}[-\s]?\d{0,3}\b")),
    ("datos_bancarios", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")),
    ("salario_individual", re.compile(r"(?i)\b(salario|sueldo|salary|pago mensual|n[oó]mina)\s+(?:individual\s+)?(?:de|of|para|for)\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+)*[^\n;|]{0,40}")),
)
_PERSON_PAYROLL = re.compile(r"(?i)\b(salario|sueldo|salary)\b.{0,12}\b(de|of|para|for)\b\s+[A-ZÁÉÍÓÚÑ]")


def redact(text: str | None) -> tuple[str, list[str]]:
    if not text:
        return "", []
    found: list[str] = []
    clean = text
    for kind, pattern in _PATTERNS:
        clean, n = pattern.subn(MARK, clean)
        if n and kind not in found:
            found.append(kind)
    return clean, found


def clean(text: str | None) -> str:
    return redact(text)[0]


def clean_any(value):
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, dict):
        return {k: clean_any(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_any(v) for v in value]
    return value


def contains_sensitive(text: str | None) -> bool:
    return bool(redact(text)[1])


def is_individual_payroll(description: str) -> bool:
    """¿Parece una línea de nómina por persona? (salario/sueldo de <Nombre>)."""
    return bool(_PERSON_PAYROLL.search(description or "")) or bool(redact(description)[1] and "salario_individual" in redact(description)[1])
