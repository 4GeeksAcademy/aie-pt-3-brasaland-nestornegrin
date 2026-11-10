"""Métricas de legibilidad para anticipar el costo de procesar un documento.

Se usa `py-readability-metrics` (Flesch-Kincaid, Gunning Fog, Flesch Reading Ease). Tres limitaciones reales, tratadas aquí:
  1. La librería exige ≥ 100 palabras: en un correo corto devuelve error → el campo queda en `None` y se explica en
     `library_error`; los conteos propios (palabras, frases, tokens estimados) siempre existen.
  2. Sus fórmulas están calibradas para INGLÉS. Para español se añade Fernández-Huerta (adaptación de Flesch), con un
     contador de sílabas heurístico: es una estimación, no una medición exacta.
  3. Necesita el modelo `punkt_tab` de NLTK (se descarga la primera vez). Sin red y sin el modelo, tampoco falla el
     pipeline: la métrica de la librería queda en `None`.
Estas cifras alimentan una decisión de COSTO (tokens y complejidad), no un juicio de calidad del texto.
"""
from __future__ import annotations

import math
import re

LIBRARY_MIN_WORDS = 100
_STOP_ES = {"de", "la", "el", "en", "y", "que", "los", "las", "para", "con", "un", "una", "por", "del", "se", "nos", "es", "su"}
_STOP_EN = {"the", "and", "of", "to", "in", "for", "is", "we", "our", "with", "that", "are", "be", "on", "as", "this", "by"}
_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’-]*")
_VOWELS = "aeiouáéíóúü"
_STRONG = "aeoáéó"
_nltk_ready: bool | None = None


def detect_language(text: str) -> str:
    words = [w.lower() for w in _WORD.findall(text)]
    es, en = sum(w in _STOP_ES for w in words), sum(w in _STOP_EN for w in words)
    return "es" if es >= en else "en"


def words_of(text: str) -> list[str]:
    return _WORD.findall(text)


def count_sentences(text: str) -> int:
    """Frases = trozos separados por .!? o por saltos de línea (los ítems de lista y títulos no llevan punto final)."""
    parts = [p for p in re.split(r"(?<=[.!?])\s+|\n+", text) if len(words_of(p)) >= 2]
    return max(1, len(parts))


def count_syllables_es(word: str) -> int:
    """Heurística: un grupo de vocales = una sílaba, salvo hiato (vocal fuerte + vocal fuerte, o í/ú acentuadas)."""
    w = word.lower()
    syllables, previous = 0, ""
    for char in w:
        if char not in _VOWELS:
            previous = ""
            continue
        if not previous or (previous in _STRONG and char in _STRONG) or char in "íú" or previous in "íú":
            syllables += 1
        previous = char
    return max(1, syllables)


def fernandez_huerta(text: str) -> float | None:
    words = words_of(text)
    if len(words) < 10:
        return None
    syllables = sum(count_syllables_es(w) for w in words)
    sentences = count_sentences(text)
    return round(206.84 - 0.60 * (syllables / len(words) * 100) - 1.02 * (sentences / len(words) * 100), 2)


def _library_metrics(text: str) -> tuple[dict, str | None]:
    global _nltk_ready
    try:
        from readability import Readability
        from readability.exceptions import ReadabilityException
    except ImportError:
        return {}, "py-readability-metrics no está instalado."

    def compute() -> dict:
        r = Readability(text)
        return {"flesch_kincaid_grade": round(r.flesch_kincaid().score, 2), "gunning_fog": round(r.gunning_fog().score, 2),
                "flesch_reading_ease": round(r.flesch().score, 2)}

    try:
        return compute(), None
    except ReadabilityException as exc:  # p. ej. menos de 100 palabras
        return {}, str(exc)
    except LookupError:  # falta el modelo punkt_tab de NLTK
        if _nltk_ready is None:
            try:
                import nltk

                _nltk_ready = bool(nltk.download("punkt_tab", quiet=True))
            except Exception:  # noqa: BLE001 - sin red: se sigue sin la métrica de la librería
                _nltk_ready = False
        if _nltk_ready:
            try:
                return compute(), None
            except Exception as exc:  # noqa: BLE001
                return {}, f"{type(exc).__name__}: {exc}"[:160]
        return {}, "Falta el modelo NLTK punkt_tab y no se pudo descargar."


def complexity(est_tokens: int, language: str, grade: float | None, huerta: float | None) -> str:
    """Nivel de costo esperado: baja / media / alta. Inglés: grado Flesch-Kincaid; español: Fernández-Huerta (las fórmulas
    inglesas sobreestiman la dificultad del español). Los umbrales están documentados en docs/agent/rfp-intake.md."""
    if est_tokens > 6000 or (language == "en" and grade is not None and grade >= 16) or (language == "es" and huerta is not None and huerta < 40):
        return "alta"
    if est_tokens > 1500 or (language == "en" and grade is not None and grade >= 12) or (language == "es" and huerta is not None and huerta < 55):
        return "media"
    return "baja"


def measure(markdown: str) -> dict:
    words = words_of(markdown)
    est_tokens = math.ceil(len(markdown) / 4)  # ≈ 4 caracteres por token (estimación estándar)
    language = detect_language(markdown)
    library, error = _library_metrics(markdown) if len(words) >= LIBRARY_MIN_WORDS else (
        {}, f"La librería requiere {LIBRARY_MIN_WORDS} palabras y el documento tiene {len(words)}.")
    result = {
        "language": language, "word_count": len(words), "sentence_count": count_sentences(markdown),
        "char_count": len(markdown), "est_tokens": est_tokens,
        "avg_words_per_sentence": round(len(words) / count_sentences(markdown), 2) if words else 0.0,
        "flesch_kincaid_grade": None, "gunning_fog": None, "flesch_reading_ease": None, **library,
        "fernandez_huerta": fernandez_huerta(markdown) if language == "es" else None, "library_error": error,
    }
    result["complexity"] = complexity(est_tokens, language, result["flesch_kincaid_grade"], result["fernandez_huerta"])
    return result
