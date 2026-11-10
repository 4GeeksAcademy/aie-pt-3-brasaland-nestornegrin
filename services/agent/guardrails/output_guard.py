"""Guardia de SALIDA: valida lo que el modelo contestó ANTES de entregarlo. No confía en que el prompt se haya cumplido.

    estructural  la respuesta existe, es texto, tiene tamaño razonable y no trae delimitadores internos
    seguridad    no filtra el system prompt (marca CANARY o tramos de las reglas internas) ni datos que nunca se revelan
                 (receta con cantidades, precios/contratos de proveedores, nómina, evaluaciones)
    contenido    small talk / trivia SIEMPRE termina reconectando con operaciones, y es breve; el PII de clientes que el
                 manager no escribió se redacta
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import policy, sensitive
from .input_guard import CONTENT, SECURITY, STRUCTURAL
from .prompts import CANARY, prompt_shingles, _words
from .text import plain

MAX_ANSWER_CHARS = 4000
MAX_CASUAL_CHARS = 420
_MARKUP = re.compile(r"</?\s*(?:datos|mensaje_usuario)[^>]*>", re.I)
_SHINGLES = prompt_shingles()
_REDIRECT_CUES = ("incidente", "stock", "inventario", "operaciones", "turno", "incident", "inventory", "operations", "shift")


@dataclass
class OutputVerdict:
    answer: str
    events: list[dict] = field(default_factory=list)
    replaced: bool = False  # la respuesta del modelo se sustituyó por una fija (hay que descartar también su propuesta de memoria)


def _event(guardrail: str, kind: str, reason: str, action: str, **detail) -> dict:
    return {"guardrail": guardrail, "kind": kind, "reason": reason, "action": action, **detail}


def leaks_prompt(answer: str) -> bool:
    if CANARY.lower() in answer.lower():
        return True
    words = _words(answer)
    return any(tuple(words[i:i + 8]) in _SHINGLES for i in range(len(words) - 7))


def _trim_sentences(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "), cut.rfind("\n"))
    return (cut[:end + 1] if end > 40 else cut.rsplit(" ", 1)[0] + "…").strip()


def _has_redirect(answer: str) -> bool:
    low = plain(answer)
    return any(cue in low for cue in _REDIRECT_CUES) and "?" in answer[-160:]


def check_output(answer, *, question: str, language: str = "es", casual: bool = False) -> OutputVerdict:
    events: list[dict] = []
    refusals = policy.REFUSALS
    lang = language if language in ("es", "en") else "es"
    if not isinstance(answer, str) or not answer.strip():
        events.append(_event("output_structure", STRUCTURAL, "empty_or_invalid_answer", "replaced"))
        return OutputVerdict(refusals["unavailable"][lang], events, replaced=True)
    text = answer.strip()
    if _MARKUP.search(text):
        text = _MARKUP.sub("", text).strip()
        events.append(_event("output_structure", STRUCTURAL, "internal_delimiters_in_answer", "sanitized"))
    if len(text) > MAX_ANSWER_CHARS:
        text = _trim_sentences(text, MAX_ANSWER_CHARS)
        events.append(_event("output_structure", STRUCTURAL, "answer_too_long", "truncated"))
    if leaks_prompt(text):
        events.append(_event("output_prompt_leak", SECURITY, "system_prompt_leak", "replaced"))
        return OutputVerdict(refusals["leak"][lang], events, replaced=True)
    reasons = sensitive.sensitive_text_reasons(text, allowed=question)
    hard = [reason for reason in reasons if reason != "dato_personal_de_cliente"]
    if hard:
        events.append(_event("output_sensitive_data", SECURITY, hard[0], "replaced"))
        return OutputVerdict(refusals["sensitive"][lang], events, replaced=True)
    if "dato_personal_de_cliente" in reasons:
        text = sensitive.redact_pii(text, question)
        events.append(_event("output_sensitive_data", CONTENT, "dato_personal_de_cliente", "redacted"))
    if casual:
        trimmed = _trim_sentences(text, MAX_CASUAL_CHARS)
        if trimmed != text:
            events.append(_event("casual_brevity", CONTENT, "casual_answer_too_long", "truncated"))
            text = trimmed
        if not _has_redirect(text):
            text = f"{text}\n\n{policy.REDIRECT[lang]}"
            events.append(_event("casual_redirect", CONTENT, "redirect_missing_in_model_answer", "redirect_appended"))
    return OutputVerdict(text, events)
