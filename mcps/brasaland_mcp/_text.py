"""Utilidades de texto."""
import unicodedata


def fold(text: str) -> str:
    """Minúsculas y sin tildes, para comparar nombres de producto."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn").strip()
