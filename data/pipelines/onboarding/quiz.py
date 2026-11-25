"""Comprobaciones de comprensión: 5 preguntas por intento (BRIEFING: entre 4 y 6) de un banco de 8 por etapa, basadas solo en el
material oficial (cada pregunta cita su sección). Umbral del 80 %. Si no se supera, cada intento siguiente usa preguntas distintas
(rotación del banco) y el agente refuerza las secciones de las preguntas falladas. Las respuestas correctas NUNCA salen de este módulo
hacia la API: solo se publican el enunciado y las opciones."""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from functools import lru_cache

from . import config


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    options: tuple[str, ...]
    answer: int
    source: str

    def public(self) -> dict:
        return {"id": self.id, "question": self.question, "options": list(self.options)}


def bank_key(stage: config.Stage, variant: str | None) -> str | None:
    if not stage.quiz:
        return None
    return f"etapa-5-{variant}" if stage.number == 5 else f"etapa-{stage.number}"


@lru_cache(maxsize=16)
def load_bank(key: str, kb_dir: str | None = None) -> tuple[Question, ...]:
    directory = (__import__("pathlib").Path(kb_dir) if kb_dir else config.KB_DIR) / "quizzes"
    raw = json.loads((directory / f"{key}.json").read_text(encoding="utf-8"))
    return tuple(Question(item["id"], item["question"], tuple(item["options"]), item["answer"], item["source"]) for item in raw)


def select(stage: config.Stage, variant: str | None, onboarding_id: str, attempt: int, kb_dir: str | None = None) -> list[Question]:
    """Preguntas del intento `attempt` (0, 1, 2…): orden estable por incorporación y ventana que rota por el banco, de modo que dos
    intentos seguidos no repiten el mismo conjunto."""
    key = bank_key(stage, variant)
    bank = list(load_bank(key, kb_dir))
    random.Random(f"{onboarding_id}:{stage.number}").shuffle(bank)
    size = min(config.QUESTIONS_PER_ATTEMPT, len(bank))
    start = (attempt * size) % len(bank)
    return [bank[(start + i) % len(bank)] for i in range(size)]


def question_by_id(stage: config.Stage, variant: str | None, question_id: str, kb_dir: str | None = None) -> Question | None:
    return next((q for q in load_bank(bank_key(stage, variant), kb_dir) if q.id == question_id), None)


@dataclass(frozen=True)
class Grade:
    correct: int
    total: int
    passed: bool
    failed_questions: tuple[str, ...]   # ids
    failed_sources: tuple[str, ...]     # secciones que hay que reforzar

    @property
    def score(self) -> float:
        return self.correct / self.total if self.total else 0.0


def grade(questions: list[Question], answers: dict[str, int]) -> Grade:
    failed = [q for q in questions if answers.get(q.id) != q.answer]
    correct = len(questions) - len(failed)
    sources = tuple(dict.fromkeys(q.source for q in failed))
    return Grade(correct, len(questions), bool(questions) and correct / len(questions) >= config.PASS_THRESHOLD,
                 tuple(q.id for q in failed), sources)
