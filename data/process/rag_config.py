"""Configuración y clientes del RAG de Brasaland (Hito 7).

Todo lo que cambia entre entornos (URLs, claves, IDs de modelo) viene del entorno / `.env`; nada está escrito a
mano en el código. Los clientes se crean de forma perezosa (la primera vez que se usan) para que importar los
módulos del RAG no exija claves ni red: así los tests unitarios corren sin `.env`.

Variables de entorno (los nombres LLM_API_KEY / LLM_API_URL / LLM_MODEL son los del tutorial del curso):

    QDRANT_URL, QDRANT_API_KEY      Qdrant (Cloud). La clave es opcional para un Qdrant local sin autenticación.
    LLM_API_KEY                     Clave del endpoint de modelos (obligatoria).
    LLM_API_URL (o LLM_BASE_URL)    URL base del endpoint compatible con OpenAI. Si falta, se usa la de OpenAI.
    EMBEDDING_MODEL                 ID del modelo de embeddings (dedicado). Por defecto text-embedding-3-small.
    GENERATION_MODEL (o LLM_MODEL)  ID del modelo de generación (chat). Por defecto gpt-4o-mini.
    EMBEDDING_BASE_URL,             Opcionales: si el modelo de embeddings vive en otro endpoint o usa otra clave.
    EMBEDDING_API_KEY
    RAG_MIN_SCORE                   Umbral mínimo de similitud coseno (por defecto, el calibrado en rag-design.md).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_DIR = REPO_ROOT / "docs" / "company-knowledge-base"

# Nombres fijados por el BRIEFING de Brasaland (Hito 7): no se cambian sin cambiar el BRIEFING.
COLLECTION_NAME = "brasaland_knowledge"
COMPANY = "brasaland"
LANGUAGE = "es"
SOURCE_DOCUMENTS = ("loyalty-program", "waste-protocol", "menu-allergens", "supplier-ordering")

# Umbral de similitud coseno por defecto. Se calibra con `scripts/evaluate_rag.py` (ver docs/rag/rag-design.md);
# se puede sobrescribir con RAG_MIN_SCORE sin tocar el código.
DEFAULT_MIN_SCORE = 0.30
DEFAULT_K = 5

# Modelos por defecto: los del tutorial del curso. Se pueden cambiar por variable de entorno sin tocar el código.
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_GENERATION_MODEL = "gpt-4o-mini"


class RagConfigError(RuntimeError):
    """Falta una variable de entorno o la configuración de modelos no es válida."""


@dataclass(frozen=True)
class RagSettings:
    qdrant_url: str
    qdrant_api_key: str | None
    embedding_model: str
    generation_model: str
    llm_base_url: str | None
    llm_api_key: str
    embedding_base_url: str | None
    embedding_api_key: str
    min_score: float


def _load_dotenv() -> None:
    """Carga el `.env` de la raíz del repo si existe (no pisa variables ya definidas en el entorno)."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv es dependencia del proyecto
        return
    load_dotenv(REPO_ROOT / ".env", override=False)


def _first(*names: str) -> str | None:
    """Valor de la primera variable de entorno definida (no vacía) entre `names`, o None."""
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return None


def _required(name: str) -> str:
    value = _first(name)
    if not value:
        raise RagConfigError(f"Falta la variable de entorno {name} (defínela en tu .env).")
    return value


def ensure_distinct_models(embedding_model: str, generation_model: str) -> None:
    """El modelo de embeddings debe ser distinto del de generación (requisito del ticket)."""
    if embedding_model.strip() == generation_model.strip():
        raise RagConfigError(
            "EMBEDDING_MODEL y GENERATION_MODEL deben ser modelos distintos: el modelo de generación "
            "nunca se reutiliza para calcular embeddings."
        )


def load_settings() -> RagSettings:
    """Lee y valida toda la configuración. Lanza `RagConfigError` con un mensaje accionable si algo falta."""
    _load_dotenv()
    embedding_model = _first("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL
    generation_model = _first("GENERATION_MODEL", "LLM_MODEL") or DEFAULT_GENERATION_MODEL
    ensure_distinct_models(embedding_model, generation_model)

    llm_api_key = _required("LLM_API_KEY")
    llm_base_url = _first("LLM_BASE_URL", "LLM_API_URL")
    raw_min_score = (os.environ.get("RAG_MIN_SCORE") or "").strip()
    try:
        min_score = float(raw_min_score) if raw_min_score else DEFAULT_MIN_SCORE
    except ValueError as error:
        raise RagConfigError(f"RAG_MIN_SCORE debe ser un número (recibido: {raw_min_score!r}).") from error

    return RagSettings(
        qdrant_url=_required("QDRANT_URL"),
        qdrant_api_key=(os.environ.get("QDRANT_API_KEY") or "").strip() or None,
        embedding_model=embedding_model,
        generation_model=generation_model,
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        embedding_base_url=(os.environ.get("EMBEDDING_BASE_URL") or "").strip() or llm_base_url,
        embedding_api_key=(os.environ.get("EMBEDDING_API_KEY") or "").strip() or llm_api_key,
        min_score=min_score,
    )


def get_qdrant_client():
    """Cliente de Qdrant (Cloud). Import perezoso: solo hace falta `qdrant-client` cuando de verdad se usa."""
    from qdrant_client import QdrantClient

    settings = load_settings()
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=30)


def get_embedding_client():
    """Cliente del endpoint de embeddings (API compatible con OpenAI)."""
    from openai import OpenAI

    settings = load_settings()
    return OpenAI(base_url=settings.embedding_base_url, api_key=settings.embedding_api_key, timeout=30)


def get_generation_client():
    """Cliente del endpoint del modelo de generación (API compatible con OpenAI)."""
    from openai import OpenAI

    settings = load_settings()
    return OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key, timeout=60)
