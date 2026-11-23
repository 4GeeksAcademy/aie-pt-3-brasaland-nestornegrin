from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SectionDraft(_Lenient):
    """Lo que devuelve el generador de un departamento."""
    content: str = Field(min_length=1)  # Markdown, texto de la sección de la propuesta económica
    pending_items: list[str] = Field(default_factory=list)  # datos que faltan y que la sección declara como pendientes


class AspectCoverage(_Lenient):
    index: int
    covered: bool
    evidence: str = ""  # fragmento TEXTUAL del borrador que cubre el aspecto (se verifica en código)


class RelevanceJudgement(_Lenient):
    aspects: list[AspectCoverage] = Field(default_factory=list)
