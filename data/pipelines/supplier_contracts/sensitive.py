"""Datos sensibles (BRIEFING): datos bancarios de los proveedores y datos personales de sus contactos (teléfono y correo personales).

Defensa en dos capas: (1) el modelo de datos no tiene ningún campo para ellos y la ingesta descarta por COMPLETO la cláusula de
facturación; (2) `redact()` sustituye por una marca cualquier cosa con forma de cuenta, teléfono o correo ANTES de guardar, registrar,
enviar entre agentes o devolver por la API. Los correos del directorio interno (@brasaland-demo.com) no son datos de contacto de proveedores."""
from __future__ import annotations

import re

MARK = "[dato sensible omitido]"
BILLING_MARK = "[cláusula de facturación: contenido omitido por contener datos sensibles]"

_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("datos_bancarios", re.compile(r"(?i)\b(cuenta|account|iban|swift|routing|aba|clabe|banco|bank|titular|holder)\b[^\n;.]{0,40}?\d[\d .\-]{5,}\d")),
    ("datos_bancarios", re.compile(r"\b\d{3,4}[-\s]\d{5,}[-\s]?\d{0,3}\b")),
    ("datos_bancarios", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")),
    ("telefono", re.compile(r"\+\d{1,3}[\s.\-]?\(?\d{2,4}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b")),
    ("telefono", re.compile(r"\(\d{3}\)\s?\d{3}[-\s]\d{4}")),
    ("telefono", re.compile(r"\b3\d{2}[\s-]\d{3}[\s-]\d{4}\b")),
    ("correo", re.compile(r"(?i)\b[\w.+-]+@(?!brasaland-demo\.com\b)[\w-]+(?:\.[\w-]+)+\b")),
)


def redact(text: str | None) -> tuple[str, list[str]]:
    """(texto sin datos sensibles, tipos detectados)."""
    if not text:
        return "", []
    found: list[str] = []
    clean = text
    for kind, pattern in _PATTERNS:
        clean, count = pattern.subn(MARK, clean)
        if count and kind not in found:
            found.append(kind)
    return clean, found


def clean(text: str | None) -> str:
    return redact(text)[0]


def clean_any(value):
    """Redacta recursivamente cualquier estructura (dict/list/str) antes de guardarla o devolverla."""
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, dict):
        return {k: clean_any(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_any(v) for v in value]
    return value


def contains_sensitive(text: str | None) -> bool:
    return bool(redact(text)[1])
