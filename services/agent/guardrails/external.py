"""Aislamiento del contenido EXTERNO: fragmentos del RAG y resultados de las tools (descripciones de tickets, nombres de
productos…). Lo escribió alguien que no es el manager ni la empresa en este turno, así que es DATO, jamás instrucción
(inyección indirecta de prompt).

Dos defensas, ambas deterministas:
  1. Sanitizar: cada frase que se dirija al modelo o intente cambiar sus reglas («ignora tus instrucciones», «asistente,
     envía…», «SYSTEM:») se sustituye por un marcador; el resto del dato se conserva (el ticket sigue siendo útil).
     Los delimitadores del prompt se neutralizan para que el texto no pueda «cerrar» el bloque de datos y abrir uno propio.
  2. Aislar: el prompt (prompts.py) entrega cada fragmento dentro de `<datos fuente="…">…</datos>` con la regla de que
     lo de dentro NUNCA se obedece.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import patterns
from .text import excerpt, strip_invisible, views

NEUTRALIZED = "[contenido externo no confiable omitido]"
MAX_CHUNK_CHARS = 3000
_SENTENCES = re.compile(r"(?<=[.!?;\n])\s+")
_TAGS = re.compile(r"<\s*/?\s*(?:datos|mensaje_usuario|mensaje|system|sistema|instrucciones|assistant|user|context\w*)[^>]*>", re.I)


@dataclass(frozen=True)
class IsolationFinding:
    source: str  # documento o tool de donde vino
    family: str  # familia de ataque detectada
    excerpt: str  # lo que se neutralizó (sin PII, recortado)


def escape_markup(text: str) -> str:
    """Neutraliza etiquetas que imitan los delimitadores del prompt o roles de chat. Quita también `<`/`>` sueltos."""
    return _TAGS.sub("", text).replace("<", "‹").replace(">", "›")


def sanitize_text(text: str, source: str = "") -> tuple[str, list[IsolationFinding]]:
    clean = strip_invisible(str(text))[:MAX_CHUNK_CHARS]
    findings: list[IsolationFinding] = []
    kept = []
    for sentence in _SENTENCES.split(clean):
        family = patterns.injection_family(views(sentence)) if sentence.strip() else None
        if family:
            findings.append(IsolationFinding(source, family, excerpt(sentence)))
            kept.append(NEUTRALIZED)
        else:
            kept.append(sentence)
    return escape_markup(" ".join(kept)), findings


def isolate_chunks(chunks: list[dict]) -> tuple[list[dict], list[IsolationFinding]]:
    """Devuelve copias saneadas de los fragmentos (no muta los originales) y lo que se neutralizó."""
    safe, findings = [], []
    for chunk in chunks:
        source = str(chunk.get("source_document", "desconocido"))
        text, found = sanitize_text(chunk.get("text", ""), source)
        findings.extend(found)
        safe.append({**chunk, "text": text, "source_document": escape_markup(source)[:120],
                     "section": escape_markup(str(chunk.get("section", "sin sección")))[:120]})
    return safe, findings
