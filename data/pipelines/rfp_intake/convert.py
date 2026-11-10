"""PDF → Markdown con MarkItDown, ANTES de que cualquier agente lea el documento (reduce tokens y ruido).

Por qué MarkItDown y no pasarle el PDF al modelo: el Markdown es texto plano estructurado (títulos, listas), cuesta una
fracción de tokens y se puede medir y cachear. Limitaciones conocidas y cómo se tratan:
  * pdfminer deja las viñetas como `(cid:127)` → se normalizan a `-`.
  * Las tablas se aplanan a líneas sueltas (pierden la alineación fila/columna) → los prompts no asumen estructura tabular.
  * Un PDF escaneado (solo imagen) no produce texto → `ConversionError`, que el pipeline convierte en un ticket `descartado`
    con el motivo explícito (nunca un fallo silencioso).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MIN_TEXT_CHARS = 20


class ConversionError(Exception):
    """El PDF no se pudo convertir o no contiene texto extraíble."""


@dataclass(frozen=True)
class Converted:
    markdown: str
    converter: str = "markitdown"


_converter = None  # MarkItDown tarda en importarse (dependencias pesadas): se crea una vez y solo cuando hace falta


def clean_markdown(text: str) -> str:
    text = re.sub(r"\(cid:127\)", "-", text)  # viñeta
    text = re.sub(r"\(cid:\d+\)", "", text)  # otros glifos sin mapa de caracteres
    text = text.replace("\r\n", "\n").replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def pdf_to_markdown(path: str | Path) -> Converted:
    global _converter
    path = Path(path)
    if not path.is_file():
        raise ConversionError(f"No existe el archivo {path.name}.")
    try:
        if _converter is None:
            from markitdown import MarkItDown

            _converter = MarkItDown()
        text = _converter.convert(str(path)).text_content or ""
    except Exception as exc:  # noqa: BLE001 - cualquier fallo del conversor se reporta con un mensaje claro
        raise ConversionError(f"No se pudo convertir el PDF: {type(exc).__name__}.") from exc
    markdown = clean_markdown(text)
    if markdown.startswith("%PDF-"):  # MarkItDown cae a «texto plano» con un PDF corrupto: devuelve los bytes crudos
        raise ConversionError("El archivo no es un PDF válido (está corrupto).")
    if len(markdown) < MIN_TEXT_CHARS:
        raise ConversionError("El PDF no contiene texto extraíble (¿es un escaneo o una imagen?).")
    return Converted(markdown)
