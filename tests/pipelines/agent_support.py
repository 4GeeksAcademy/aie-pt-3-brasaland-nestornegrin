"""Dobles de prueba compartidos por los tests y los evals del agente (sin red, sin claves, sin modelos reales)."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from types import SimpleNamespace

from services.agent.nodes import AgentDependencies


def fake_embed(text: str, dim: int = 128) -> list[float]:
    """Embedding falso y determinista (bolsa de palabras con hash), el mismo criterio que usa `test_rag.py`."""
    normalized = unicodedata.normalize("NFD", text.lower())
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    vector = [0.0] * dim
    for token in re.findall(r"\w+", normalized):
        if len(token) >= 3:
            vector[int(hashlib.md5(token.encode()).hexdigest(), 16) % dim] += 1.0
    if not any(vector):
        vector[0] = 1.0
    return vector


def chunk(source: str, section: str, text: str, index: int = 0) -> dict:
    return {"company": "brasaland", "source_document": source, "section": section, "language": "es",
            "chunk_index": index, "text": text}


class SpyDependencies:
    """Dependencias del agente que registran cuántas veces se llamó a cada paso y con qué argumentos."""

    def __init__(self, context: list[dict] | None = None, answer: str = "Respuesta de prueba."):
        self.context = context if context is not None else [chunk("loyalty-program", "Niveles", "Oro: 50+ puntos.")]
        self.answer = answer
        self.retrieve_calls: list[str] = []
        self.generate_calls: list[tuple[str, list[dict]]] = []

    def retrieve(self, question: str) -> list[dict]:
        self.retrieve_calls.append(question)
        return list(self.context)

    def generate(self, question: str, context: list[dict]) -> str:
        self.generate_calls.append((question, context))
        return self.answer

    @property
    def deps(self) -> AgentDependencies:
        return AgentDependencies(retrieve_fn=self.retrieve, generate_fn=self.generate)


def extractive_generate(question: str, context: list[dict]) -> str:
    """Sustituto determinista del modelo de chat: responde con el texto de los fragmentos recuperados y su fuente.
    Sirve para comprobar que la respuesta del agente sale de la base de conocimiento y no de otro sitio."""
    if not context:
        raise AssertionError("generate_answer no debe ejecutarse sin contexto recuperado")
    body = "\n".join(item["text"] for item in context)
    sources = "\n".join(f"Fuente: {item['source_document']} — {item['section']}" for item in context)
    return f"{body}\n\n{sources}"


def stub_point(score: float, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(score=score, payload=payload)
