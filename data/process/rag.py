"""Fase 1 del RAG de Brasaland: preparar los datos y guardarlos en Qdrant.

Responsabilidades de este módulo (cada una en su propia función, para poder reemplazar cualquiera sin tocar el resto):

    load_documents()    lee los Markdown de `docs/company-knowledge-base/`.
    chunk_document()    divide un documento en chunks semánticos (nunca corta una frase ni una regla).
    embed()             convierte un texto en un vector con el modelo de embeddings (dedicado).
    setup()             orquesta todo: chunking -> embeddings -> colección de Qdrant -> puntos.

Por qué el chunking es "por bloques" y no por tamaño fijo: los cuatro documentos fuente son cortos (≈25 líneas) y no
tienen encabezados `##`; cada bloque separado por una línea en blanco es una idea completa (una política, una lista
de niveles, un grupo de pasos). Se usa el bloque como unidad, se une con el siguiente cuando ambos hablan de lo mismo
(misma sección) y solo se divide si un bloque supera `MAX_CHARS`, siempre en el límite de un ítem o de una frase.
Más detalle y justificación en `docs/rag/rag-design.md`.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from data.process.rag_config import (
    COLLECTION_NAME,
    COMPANY,
    KNOWLEDGE_BASE_DIR,
    LANGUAGE,
    SOURCE_DOCUMENTS,
    get_embedding_client,
    get_qdrant_client,
    load_settings,
)

# Tamaño máximo aproximado de un chunk. Los bloques de los documentos de Brasaland miden 170-560 caracteres, así
# que en la práctica ningún bloque se divide; el límite existe para que documentos futuros más largos no generen
# chunks enormes.
MAX_CHARS = 800

# Espacio de nombres fijo para derivar IDs deterministas (uuid5): mismo documento + mismo índice = mismo ID.
_POINT_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "brasaland-knowledge")

# Los documentos fuente no traen encabezados `##`: el nombre de cada sección se asigna por las primeras palabras del
# bloque. Los bloques consecutivos con la misma etiqueta se unen en un solo chunk. Si un bloque no coincide con
# ninguna regla, la sección es su primera frase (ver `_section_label`).
SECTION_LABELS: dict[str, tuple[tuple[str, str], ...]] = {
    "loyalty-program": (
        ("Brasa Points es el programa", "Acumulación y vigencia de puntos"),
        ("Niveles del programa", "Niveles del programa"),
        ("Los puntos se pueden redimir", "Redención de puntos"),
        ("El programa está disponible", "Tarjeta física y app digital"),
        ("Preguntas frecuentes de clientes", "Preguntas frecuentes de clientes"),
    ),
    "waste-protocol": (
        ("Todo local Brasaland debe registrar", "Categorías de desperdicio"),
        ("Procedimiento diario", "Procedimiento diario"),
        ("Causas comunes de desperdicio", "Causas aceptadas sin nota adicional"),
        ("Causas que requieren escalamiento", "Escalamiento a Felipe Guerrero"),
        ("Meta operativa", "Meta operativa y plan de mejora"),
    ),
    "menu-allergens": (
        ("Brasaland reporta alérgenos", "Normativa y criterio de alérgenos"),
        ("Platos principales y sus alérgenos", "Alérgenos declarados por plato"),
        ("Protocolo ante alergias", "Protocolo ante alergias reportadas"),
        ("No existe versión sin gluten", "Costillas BBQ: sin versión sin gluten certificada"),
    ),
    "supplier-ordering": (
        ("Cada gerente de local", "Responsable y horario del pedido semanal"),
        ("Categorías de proveedores", "Frecuencia de pedido por categoría"),
        ("Regla de stock mínimo", "Stock mínimo y pedido de emergencia"),
        ("Un pedido de emergencia requiere", "Stock mínimo y pedido de emergencia"),
    ),
}

_LIST_ITEM = re.compile(r"^(?:[-*]\s+|\d+[.)]\s+)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class KnowledgeBaseError(RuntimeError):
    """Los documentos fuente no están donde `setup()` los espera, o no son los que pide el BRIEFING."""


@dataclass(frozen=True)
class SourceDocument:
    source_document: str  # slug del BRIEFING: loyalty-program | waste-protocol | menu-allergens | supplier-ordering
    title: str  # el `# Título` del Markdown
    text: str
    path: Path


@dataclass(frozen=True)
class Chunk:
    source_document: str
    title: str
    section: str
    chunk_index: int
    text: str  # cuerpo del chunk: es lo que se inserta en el prompt de generación

    @property
    def point_id(self) -> str:
        """ID determinista: volver a ejecutar `setup()` actualiza el mismo punto en vez de duplicarlo."""
        return str(uuid.uuid5(_POINT_ID_NAMESPACE, f"{self.source_document}/{self.chunk_index}"))

    @property
    def embedding_text(self) -> str:
        """Texto que se embebe: el cuerpo precedido por el título del documento y la sección (contexto)."""
        return f"{self.title}. {self.section}.\n{self.text}"

    def payload(self) -> dict:
        """Payload del punto: los campos que fija el BRIEFING (`company`, `language`, ...) más `text`."""
        return {
            "company": COMPANY,
            "source_document": self.source_document,
            "section": self.section,
            "language": LANGUAGE,
            "chunk_index": self.chunk_index,
            "text": self.text,
        }


@dataclass
class _Block:
    """Un bloque del Markdown: un párrafo, o una frase de introducción seguida de su lista."""

    lead: str = ""
    items: list[str] = field(default_factory=list)
    heading: str | None = None  # encabezado `##` vigente, si el documento los tiene

    def render(self) -> str:
        return "\n".join(part for part in [self.lead, *self.items] if part)

    @property
    def length(self) -> int:
        return len(self.render())


# --------------------------------------------------------------------------------------------------------------
# Lectura y parseo
# --------------------------------------------------------------------------------------------------------------
def source_slug(path: Path) -> str:
    """`brasaland-loyalty-program.es.md` -> `loyalty-program` (el valor que exige el BRIEFING en el payload)."""
    name = path.name
    for prefix in ("brasaland-",):
        if name.startswith(prefix):
            name = name[len(prefix):]
    for suffix in (".es.md", ".md"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name


def load_documents(docs_dir: Path | str = KNOWLEDGE_BASE_DIR) -> list[SourceDocument]:
    """Lee los cuatro documentos fuente. Falla con un mensaje claro si falta alguno o sobra un desconocido."""
    directory = Path(docs_dir)
    if not directory.is_dir():
        raise KnowledgeBaseError(f"No existe la carpeta de documentos fuente: {directory}")

    documents = []
    for path in sorted(directory.glob("brasaland-*.md")):
        slug = source_slug(path)
        if slug not in SOURCE_DOCUMENTS:
            continue  # un .md ajeno al BRIEFING no se indexa
        text = path.read_text(encoding="utf-8")
        match = next((m for line in text.splitlines() if (m := _HEADING.match(line)) and len(m.group(1)) == 1), None)
        title = match.group(2) if match else slug
        documents.append(SourceDocument(source_document=slug, title=title, text=text, path=path))

    missing = sorted(set(SOURCE_DOCUMENTS) - {doc.source_document for doc in documents})
    if missing:
        raise KnowledgeBaseError(
            f"Faltan documentos fuente en {directory}: {', '.join(missing)}. "
            "Cópialos desde 00-general-contexts/brasaland/ (ver el BRIEFING)."
        )
    return documents


def _parse_blocks(text: str) -> list[_Block]:
    """Divide el Markdown en bloques. Une las líneas partidas de un mismo párrafo o ítem (los .md están
    ajustados a ~78 columnas) y conserva la lista junto a su frase de introducción."""
    blocks: list[_Block] = []
    current_heading: str | None = None
    for raw_block in re.split(r"\n\s*\n", text.strip()):
        block = _Block(heading=current_heading)
        lead_parts: list[str] = []
        for line in raw_block.splitlines():
            if not line.strip():
                continue
            heading = _HEADING.match(line)
            if heading:
                if len(heading.group(1)) > 1:
                    current_heading = heading.group(2)
                    block.heading = current_heading
                continue  # el `# Título` y los `##` no son contenido del chunk
            if _LIST_ITEM.match(line.strip()) and not line.startswith(" "):
                block.items.append(line.strip())
            elif block.items:
                block.items[-1] += " " + line.strip()  # continuación (sangrada) del ítem anterior
            else:
                lead_parts.append(line.strip())
        block.lead = " ".join(lead_parts)
        if block.lead or block.items:
            blocks.append(block)
    return blocks


def _section_label(slug: str, block: _Block) -> str:
    if block.heading:
        return block.heading
    for prefix, label in SECTION_LABELS.get(slug, ()):
        if (block.lead or block.items[0]).startswith(prefix):
            return label
    first = (block.lead or block.items[0]).strip()
    return _SENTENCE_END.split(first, maxsplit=1)[0].rstrip(":.")[:80]


def _split_oversized(block: _Block) -> list[str]:
    """Divide un bloque demasiado largo sin cortar nada por la mitad: por ítems (repitiendo la frase de
    introducción para que cada trozo se entienda solo) o, si es un párrafo, por frases."""
    if block.length <= MAX_CHARS:
        return [block.render()]
    pieces: list[str] = []
    if block.items:
        group: list[str] = []
        for item in block.items:
            candidate = _Block(lead=block.lead, items=[*group, item])
            if group and candidate.length > MAX_CHARS:
                pieces.append(_Block(lead=block.lead, items=group).render())
                group = []
            group.append(item)
        if group:
            pieces.append(_Block(lead=block.lead, items=group).render())
        return pieces
    current = ""
    for sentence in _SENTENCE_END.split(block.lead):
        if current and len(current) + 1 + len(sentence) > MAX_CHARS:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def chunk_document(document: SourceDocument) -> list[Chunk]:
    """Divide un documento en chunks semánticos coherentes, numerados desde 0."""
    grouped: list[tuple[str, list[_Block]]] = []
    for block in _parse_blocks(document.text):
        label = _section_label(document.source_document, block)
        if grouped and grouped[-1][0] == label and sum(b.length for b in grouped[-1][1]) + block.length <= MAX_CHARS:
            grouped[-1][1].append(block)  # misma sección y cabe: un solo chunk
        else:
            grouped.append((label, [block]))

    chunks: list[Chunk] = []
    for label, blocks in grouped:
        if len(blocks) == 1:
            bodies = _split_oversized(blocks[0])
        else:
            bodies = ["\n".join(b.render() for b in blocks)]
        for body in bodies:
            chunks.append(
                Chunk(
                    source_document=document.source_document,
                    title=document.title,
                    section=label,
                    chunk_index=len(chunks),
                    text=body,
                )
            )
    return chunks


def build_chunks(docs_dir: Path | str = KNOWLEDGE_BASE_DIR) -> list[Chunk]:
    """Todos los chunks de todos los documentos fuente, en un orden estable."""
    chunks: list[Chunk] = []
    for document in load_documents(docs_dir):
        chunks.extend(chunk_document(document))
    return chunks


# --------------------------------------------------------------------------------------------------------------
# Embeddings
# --------------------------------------------------------------------------------------------------------------
def normalize_text(text: str) -> str:
    """Único preprocesado antes de embeber: recorta y colapsa espacios y saltos de línea. No se pasa a minúsculas
    ni se quitan tildes: el modelo de embeddings las entiende y quitarlas podría confundir palabras."""
    return " ".join(text.split())


def embed(text: str) -> list[float]:
    """Vector del texto con el modelo de embeddings dedicado (`EMBEDDING_MODEL`).

    Es la MISMA función para indexar los chunks y para embeber la pregunta del usuario: así ambos viven en el mismo
    espacio vectorial. Nunca usa el modelo de generación."""
    cleaned = normalize_text(text)
    if not cleaned:
        raise ValueError("embed() necesita un texto no vacío.")
    settings = load_settings()
    response = get_embedding_client().embeddings.create(model=settings.embedding_model, input=cleaned)
    return [float(value) for value in response.data[0].embedding]


# --------------------------------------------------------------------------------------------------------------
# Qdrant
# --------------------------------------------------------------------------------------------------------------
def _ensure_collection(client, vector_size: int) -> None:
    """Crea la colección si no existe; la recrea solo si el tamaño del vector o la métrica ya no coinciden."""
    from qdrant_client.models import Distance, VectorParams

    if client.collection_exists(COLLECTION_NAME):
        params = client.get_collection(COLLECTION_NAME).config.params.vectors
        if getattr(params, "size", None) == vector_size and getattr(params, "distance", None) == Distance.COSINE:
            return
        client.delete_collection(COLLECTION_NAME)
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )


def _delete_stale_points(client, keep_ids: set[str]) -> int:
    """Borra los puntos que ya no corresponden a ningún chunk (p. ej. un documento que ahora es más corto)."""
    from qdrant_client.models import PointIdsList

    stale: list[str] = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=COLLECTION_NAME, limit=256, offset=offset, with_payload=False, with_vectors=False
        )
        stale.extend(str(point.id) for point in points if str(point.id) not in keep_ids)
        if offset is None:
            break
    if stale:
        client.delete(collection_name=COLLECTION_NAME, points_selector=PointIdsList(points=stale), wait=True)
    return len(stale)


def setup(
    docs_dir: Path | str = KNOWLEDGE_BASE_DIR,
    *,
    client=None,
    embed_fn: Callable[[str], list[float]] | None = None,
) -> dict:
    """Indexa la base de conocimiento: lee y divide los documentos, crea la colección y guarda los chunks.

    Idempotente: cada punto tiene un ID determinista (uuid5 de documento + índice de chunk) y se guarda con `upsert`,
    así que ejecutarla de nuevo actualiza los mismos puntos en vez de duplicarlos; además borra los puntos huérfanos.
    Devuelve un resumen (colección, nº de chunks, chunks por documento, tamaño del vector)."""
    from qdrant_client.models import PointStruct

    chunks = build_chunks(docs_dir)
    client = client if client is not None else get_qdrant_client()
    embed_fn = embed_fn if embed_fn is not None else embed

    vectors = [embed_fn(chunk.embedding_text) for chunk in chunks]
    vector_size = len(vectors[0])
    if any(len(vector) != vector_size for vector in vectors):
        raise ValueError("embed() devolvió vectores de distinto tamaño.")

    _ensure_collection(client, vector_size)
    client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            PointStruct(id=chunk.point_id, vector=vector, payload=chunk.payload())
            for chunk, vector in zip(chunks, vectors)
        ],
        wait=True,
    )
    removed = _delete_stale_points(client, {chunk.point_id for chunk in chunks})

    per_document: dict[str, int] = {}
    for chunk in chunks:
        per_document[chunk.source_document] = per_document.get(chunk.source_document, 0) + 1
    return {
        "collection": COLLECTION_NAME,
        "chunks": len(chunks),
        "per_document": per_document,
        "vector_size": vector_size,
        "stale_points_removed": removed,
    }


if __name__ == "__main__":  # pragma: no cover - uso manual: `uv run python -m data.process.rag`
    import json

    print(json.dumps(setup(), indent=2, ensure_ascii=False))
