"""Normalización de texto para los guardrails.

Un filtro que solo mira el texto tal cual se evade con tildes, mayúsculas, letras separadas («i g n o r a»), caracteres
invisibles, homoglifos cirílicos o «leetspeak» («1gn0r4»). Cada detector mira VARIAS vistas del mismo mensaje:

    plain      minúsculas, sin tildes, sin caracteres invisibles
    deobf      plain + homoglifos y leetspeak traducidos a letras
    collapsed  deobf con las letras sueltas pegadas («i g n o r a» -> «ignora»)
    decoded    texto de los fragmentos base64 que parezcan texto legible
"""
from __future__ import annotations

import base64
import binascii
import re
import unicodedata

# Cirílico/griego que se parece a una letra latina (la lista corta que usan los ataques reales).
_HOMOGLYPHS = str.maketrans({"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ѕ": "s",
                             "ј": "j", "ԁ": "d", "ɡ": "g", "ο": "o", "α": "a", "ε": "e", "ι": "i", "ρ": "p", "ν": "v"})
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i", "|": "l"})
_SPACED_LETTERS = re.compile(r"(?<!\w)(?:\w[\s.\-_*]+){3,}\w(?!\w)")
_BASE64 = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")


def strip_invisible(text: str) -> str:
    """Quita caracteres de formato/control (espacios de ancho cero, marcas bidireccionales...) que no se ven."""
    return "".join(char for char in text if unicodedata.category(char) not in ("Cf", "Cc") or char in "\n\t")


def plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", strip_invisible(text).lower())
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def deobfuscate(text: str) -> str:
    return plain(text).translate(_HOMOGLYPHS).translate(_LEET)


def collapse_spaced_letters(text: str) -> str:
    return _SPACED_LETTERS.sub(lambda match: re.sub(r"[\s.\-_*]+", "", match.group(0)), text)


_SPACED_WORD = re.compile(r"(?<!\w)(?:\w[ .\-_*]){3,}\w(?!\w)")


def collapse_spaced_words(text: str) -> str:
    """Como `collapse_spaced_letters`, pero conserva los límites de palabra cuando van separados por 2+ espacios."""
    return _SPACED_WORD.sub(lambda match: re.sub(r"[ .\-_*]", "", match.group(0)), text)


def decoded_base64(text: str) -> list[str]:
    """Texto legible escondido en fragmentos base64 del mensaje (técnica habitual para colar instrucciones)."""
    found = []
    for token in _BASE64.findall(text):
        try:
            raw = base64.b64decode(token + "=" * (-len(token) % 4), validate=False)
            decoded = raw.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if decoded and sum(char.isprintable() or char.isspace() for char in decoded) / len(decoded) > 0.95:
            found.append(decoded)
    return found


def views(text: str) -> list[str]:
    """Todas las vistas del mensaje sobre las que se buscan patrones."""
    base = plain(text)
    deobf = deobfuscate(text)
    collapsed = collapse_spaced_letters(deobf)
    words = collapse_spaced_words(deobf)
    extra = [plain(item) for item in decoded_base64(text)]
    return list(dict.fromkeys([base, deobf, words, collapsed, *extra]))


# Para el registro: sin correos ni teléfonos y con tope de tamaño.
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_DIGITS = re.compile(r"(?:\+?\d[\s().-]?){7,}")


def excerpt(text: str, limit: int = 120) -> str:
    return _DIGITS.sub("[número]", _EMAIL.sub("[correo]", strip_invisible(text))).strip().replace("\n", " ")[:limit]


_ENGLISH = frozenset("the and you your what how can could please ignore are is do does this that with for from about "
                     "tell show write give me my now all any".split())
_SPANISH = frozenset("el la los las que de del por para como puedes puedo eres soy mi tu tus una un con sin esto esta "
                     "dime muestra escribe dame ahora todo todas cuál cuáles qué cómo".split())


def detect_language(text: str) -> str:
    words = re.findall(r"[a-záéíóúñü]+", text.lower())
    english, spanish = sum(w in _ENGLISH for w in words), sum(w in _SPANISH for w in words)
    return "en" if english > spanish else "es"
