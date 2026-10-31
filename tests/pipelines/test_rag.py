"""Pruebas unitarias del RAG de Brasaland (Hito 7): chunking, setup(), retrieve(), generate_answer() y query().

Ninguna prueba usa Qdrant Cloud ni un LLM reales (el ticket lo prohíbe en CI):

* `retrieve()` se prueba con un cliente de Qdrant simulado (`StubQdrant`) cuyas puntuaciones controla el test.
* `query()` se prueba simulando `retrieve()` y la llamada al LLM de generación.
* `setup()` y la búsqueda completa se prueban con el modo en memoria de `qdrant-client` (`QdrantClient(":memory:")`)
  y un embedding falso determinista (bolsa de palabras con hash), que no requiere red.

Se ejecutan con `python -m pytest tests/pipelines/test_rag.py` (o `uv run pytest tests/pipelines/test_rag.py`).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import pytest
from qdrant_client import QdrantClient

from data.pipelines import rag as pipeline
from data.process import rag as process
from data.process import rag_config
from scripts import evaluate_rag

DOCS_DIR = rag_config.KNOWLEDGE_BASE_DIR
QUERIES_PATH = Path(__file__).resolve().parents[2] / "data" / "eval" / "test-queries.json"
BRIEFING_PAYLOAD_FIELDS = {"company", "source_document", "section", "language", "chunk_index", "text"}


# --------------------------------------------------------------------------------------------------------------
# Dobles de prueba
# --------------------------------------------------------------------------------------------------------------
def fake_embed(text: str, dim: int = 128) -> list[float]:
    """Embedding falso y determinista: bolsa de palabras (sin tildes, ≥3 letras) con hash a `dim` dimensiones.
    Dos textos que comparten palabras tienen alta similitud coseno; no necesita red ni claves."""
    normalized = unicodedata.normalize("NFD", text.lower())
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    vector = [0.0] * dim
    for token in re.findall(r"\w+", normalized):
        if len(token) >= 3:
            vector[int(hashlib.md5(token.encode()).hexdigest(), 16) % dim] += 1.0
    if not any(vector):
        vector[0] = 1.0
    return vector


class StubQdrant:
    """Cliente de Qdrant simulado: devuelve resultados con las puntuaciones que fija el test y registra la llamada."""

    def __init__(self, hits: list[tuple[float, dict]]):
        self._hits = hits
        self.calls: list[dict] = []

    def query_points(self, **kwargs):
        self.calls.append(kwargs)
        points = [SimpleNamespace(score=score, payload=payload) for score, payload in self._hits]
        return SimpleNamespace(points=points[: kwargs["limit"]])


def chunk_payload(source: str, section: str, text: str, index: int = 0) -> dict:
    return {"company": "brasaland", "source_document": source, "section": section, "language": "es",
            "chunk_index": index, "text": text}


@pytest.fixture
def memory_client() -> QdrantClient:
    return QdrantClient(":memory:")


@pytest.fixture
def indexed_client(memory_client) -> QdrantClient:
    process.setup(client=memory_client, embed_fn=fake_embed)
    return memory_client


@pytest.fixture
def no_dotenv(monkeypatch):
    """Que ningún `.env` real (el del Codespace) interfiera con las pruebas de configuración."""
    monkeypatch.setattr(rag_config, "_load_dotenv", lambda: None)
    for name in ("EMBEDDING_MODEL", "GENERATION_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "QDRANT_URL",
                 "QDRANT_API_KEY", "RAG_MIN_SCORE", "EMBEDDING_BASE_URL", "EMBEDDING_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# --------------------------------------------------------------------------------------------------------------
# retrieve()
# --------------------------------------------------------------------------------------------------------------
HITS = [
    (0.82, chunk_payload("loyalty-program", "Niveles del programa", "Oro (50+ puntos): 15% de descuento.", 1)),
    (0.55, chunk_payload("loyalty-program", "Redención de puntos", "Desde 15 puntos.", 2)),
    (0.31, chunk_payload("waste-protocol", "Procedimiento diario", "Pesar al cierre.", 1)),
    (0.12, chunk_payload("supplier-ordering", "Frecuencia de pedido por categoría", "Semanal.", 1)),
]


def test_retrieve_excludes_results_below_min_score():
    results = pipeline.retrieve("¿nivel Oro?", k=5, min_score=0.5, client=StubQdrant(HITS), embed_fn=fake_embed)
    assert [r["section"] for r in results] == ["Niveles del programa", "Redención de puntos"]


def test_retrieve_can_return_fewer_than_k():
    results = pipeline.retrieve("pregunta", k=4, min_score=0.5, client=StubQdrant(HITS), embed_fn=fake_embed)
    assert len(results) == 2 < 4


def test_retrieve_returns_nothing_when_no_result_reaches_the_threshold():
    results = pipeline.retrieve("capital de Francia", k=5, min_score=0.95, client=StubQdrant(HITS), embed_fn=fake_embed)
    assert results == []


def test_retrieve_threshold_is_inclusive():
    results = pipeline.retrieve("x", k=5, min_score=0.55, client=StubQdrant(HITS), embed_fn=fake_embed)
    assert [r["section"] for r in results] == ["Niveles del programa", "Redención de puntos"]


def test_retrieve_returns_plain_payload_dicts_without_scores():
    results = pipeline.retrieve("x", k=5, min_score=0.0, client=StubQdrant(HITS), embed_fn=fake_embed)
    assert all(type(item) is dict for item in results)
    assert all("score" not in item for item in results)
    assert results[0] == HITS[0][1] and results[0] is not HITS[0][1]  # copia del payload, no el objeto del SDK


def test_retrieve_embeds_the_question_with_embed_and_searches_the_brasaland_collection():
    stub = StubQdrant(HITS)
    seen: list[str] = []

    def spy_embed(text: str) -> list[float]:
        seen.append(text)
        return fake_embed(text)

    pipeline.retrieve("¿cuántos puntos?", k=3, min_score=0.0, client=stub, embed_fn=spy_embed)
    assert seen == ["¿cuántos puntos?"]
    call = stub.calls[0]
    assert call["collection_name"] == "brasaland_knowledge"
    assert call["limit"] == 3
    assert call["query"] == fake_embed("¿cuántos puntos?")


@pytest.mark.parametrize("bad_query", ["", "   ", None])
def test_retrieve_rejects_an_empty_query(bad_query):
    with pytest.raises(ValueError):
        pipeline.retrieve(bad_query, k=5, min_score=0.3, client=StubQdrant(HITS), embed_fn=fake_embed)


def test_retrieve_rejects_a_non_positive_k():
    with pytest.raises(ValueError):
        pipeline.retrieve("x", k=0, min_score=0.3, client=StubQdrant(HITS), embed_fn=fake_embed)


def test_retrieve_end_to_end_on_an_in_memory_index(indexed_client):
    """Con el índice real (en memoria): una pregunta sobre el nivel Oro encuentra el chunk de niveles."""
    results = pipeline.retrieve("¿Cuántos puntos necesito para el nivel Oro?", k=3, min_score=0.0,
                                client=indexed_client, embed_fn=fake_embed)
    assert ("loyalty-program", "Niveles del programa") in [(r["source_document"], r["section"]) for r in results]
    assert set(results[0]) == BRIEFING_PAYLOAD_FIELDS


def test_retrieve_end_to_end_applies_the_threshold(indexed_client):
    results = pipeline.retrieve("¿Cuál es la capital de Francia?", k=5, min_score=0.9,
                                client=indexed_client, embed_fn=fake_embed)
    assert results == []


# --------------------------------------------------------------------------------------------------------------
# generate_answer() y query()
# --------------------------------------------------------------------------------------------------------------
CONTEXT = [chunk_payload("loyalty-program", "Niveles del programa", "Oro (50+ puntos): 15% de descuento.", 1)]


def test_query_returns_the_model_output_not_the_raw_chunks(monkeypatch):
    monkeypatch.setattr(pipeline, "retrieve", lambda question, **kw: CONTEXT)
    monkeypatch.setattr(pipeline, "complete", lambda messages: "Necesitas 50 puntos para el nivel Oro.")
    answer = pipeline.query("¿Cuántos puntos necesito para el nivel Oro?")
    assert answer == "Necesitas 50 puntos para el nivel Oro."
    assert CONTEXT[0]["text"] not in answer  # el texto crudo del chunk no se devuelve


def test_query_is_retrieve_plus_generate_answer(monkeypatch):
    calls: dict = {}

    def fake_retrieve(question, **kwargs):
        calls["retrieve"] = question
        return CONTEXT

    def fake_generate(question, context, **kwargs):
        calls["generate"] = (question, context)
        return "respuesta"

    monkeypatch.setattr(pipeline, "retrieve", fake_retrieve)
    monkeypatch.setattr(pipeline, "generate_answer", fake_generate)
    assert pipeline.query("pregunta") == "respuesta"
    assert calls["retrieve"] == "pregunta"
    assert calls["generate"][0] == "pregunta" and calls["generate"][1] is CONTEXT


def test_query_without_context_still_goes_through_the_model(monkeypatch):
    """Si retrieve() no devuelve nada, el modelo recibe un contexto vacío y la instrucción de admitirlo."""
    captured: list[list[dict]] = []

    def fake_complete(messages):
        captured.append(messages)
        return "No tengo información suficiente en la base de conocimiento de Brasaland."

    monkeypatch.setattr(pipeline, "retrieve", lambda question, **kw: [])
    monkeypatch.setattr(pipeline, "complete", fake_complete)
    answer = pipeline.query("¿Cuál es la capital de Francia?")
    assert answer.startswith("No tengo información suficiente")
    user_message = captured[0][1]["content"]
    assert pipeline.NO_CONTEXT_MARKER in user_message
    assert "Nunca inventes datos de la empresa" in captured[0][0]["content"]


def test_system_prompt_keeps_no_information_answers_clean():
    """Sin información: respuesta corta, sin hablar del 'contexto' interno ni de fuentes."""
    assert 'sin mencionar "contexto"' in pipeline.SYSTEM_PROMPT
    assert 'sin línea de "Fuente"' in pipeline.SYSTEM_PROMPT


def _fake_generation_client(contents: list):
    """Cliente de chat simulado que devuelve, en orden, los `content` indicados (None = respuesta vacía)."""
    calls: list[dict] = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=contents[len(calls) - 1]))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return client, calls


def _patch_generation(monkeypatch, client):
    monkeypatch.setattr(pipeline, "load_settings", lambda: SimpleNamespace(generation_model="modelo-chat"))
    monkeypatch.setattr(pipeline, "get_generation_client", lambda: client)


def test_complete_retries_once_when_the_model_returns_no_content(monkeypatch):
    client, calls = _fake_generation_client([None, "  Respuesta válida.  "])
    _patch_generation(monkeypatch, client)
    assert pipeline.complete([{"role": "user", "content": "hola"}]) == "Respuesta válida."
    assert len(calls) == 2 and calls[0]["model"] == "modelo-chat" and calls[0]["temperature"] == 0.0


def test_complete_raises_instead_of_returning_a_blank_answer(monkeypatch):
    client, calls = _fake_generation_client([None, ""])
    _patch_generation(monkeypatch, client)
    with pytest.raises(pipeline.EmptyCompletionError):
        pipeline.complete([{"role": "user", "content": "hola"}])
    assert len(calls) == pipeline.EMPTY_COMPLETION_ATTEMPTS


def test_generate_answer_prompt_carries_the_briefing_voice_and_the_sources():
    captured: list[list[dict]] = []
    pipeline.generate_answer("¿Cuántos puntos para Oro?", CONTEXT,
                             complete_fn=lambda messages: captured.append(messages) or "ok")
    system, user = captured[0][0]["content"], captured[0][1]["content"]
    assert "vendedor entrenado" in system
    assert "gerentes de local" in system
    assert "ÚNICAMENTE" in system  # solo el contexto recuperado
    assert "sin riesgo" in system and "no conviertas monedas" in system
    assert "[loyalty-program — Niveles del programa]" in user  # fuente trazable
    assert "Oro (50+ puntos): 15% de descuento." in user
    assert user.rstrip().endswith("¿Cuántos puntos para Oro?")


def test_generate_answer_returns_what_the_model_returns():
    assert pipeline.generate_answer("q", CONTEXT, complete_fn=lambda messages: "texto del modelo") == "texto del modelo"


@pytest.mark.parametrize("bad_question", ["", "   "])
def test_generate_answer_rejects_an_empty_question(bad_question):
    with pytest.raises(ValueError):
        pipeline.generate_answer(bad_question, CONTEXT, complete_fn=lambda messages: "x")


# --------------------------------------------------------------------------------------------------------------
# Configuración y modelos
# --------------------------------------------------------------------------------------------------------------
def test_embedding_and_generation_models_must_be_different(no_dotenv):
    for name, value in {"QDRANT_URL": "https://q", "LLM_API_KEY": "k", "EMBEDDING_MODEL": "mismo-modelo",
                        "GENERATION_MODEL": "mismo-modelo"}.items():
        no_dotenv.setenv(name, value)
    with pytest.raises(rag_config.RagConfigError, match="distintos"):
        rag_config.load_settings()


def test_missing_configuration_raises_a_clear_error(no_dotenv):
    with pytest.raises(rag_config.RagConfigError, match="EMBEDDING_MODEL"):
        rag_config.load_settings()
    no_dotenv.setenv("EMBEDDING_MODEL", "emb")
    no_dotenv.setenv("GENERATION_MODEL", "chat")
    with pytest.raises(rag_config.RagConfigError, match="LLM_API_KEY"):
        rag_config.load_settings()
    no_dotenv.setenv("LLM_API_KEY", "k")
    with pytest.raises(rag_config.RagConfigError, match="QDRANT_URL"):
        rag_config.load_settings()


def test_model_ids_are_required_and_never_defaulted(no_dotenv):
    no_dotenv.setenv("QDRANT_URL", "https://q")
    no_dotenv.setenv("LLM_API_KEY", "k")
    with pytest.raises(rag_config.RagConfigError, match="EMBEDDING_MODEL"):
        rag_config.load_settings()
    no_dotenv.setenv("EMBEDDING_MODEL", "emb")
    with pytest.raises(rag_config.RagConfigError, match="GENERATION_MODEL"):
        rag_config.load_settings()
    no_dotenv.setenv("GENERATION_MODEL", "chat")
    settings = rag_config.load_settings()
    assert (settings.embedding_model, settings.generation_model) == ("emb", "chat")
    assert settings.llm_base_url is None  # sin URL propia se usa la del SDK


def test_embed_asks_for_plain_float_vectors(no_dotenv, monkeypatch):
    for name, value in {"QDRANT_URL": "https://q", "LLM_API_KEY": "k", "EMBEDDING_MODEL": "emb",
                        "GENERATION_MODEL": "chat"}.items():
        no_dotenv.setenv(name, value)
    calls = []

    class FakeEmbeddings:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(data=[SimpleNamespace(embedding=[1, 2, 3])])

    monkeypatch.setattr(process, "get_embedding_client", lambda: SimpleNamespace(embeddings=FakeEmbeddings()))
    assert process.embed("  hola   mundo ") == [1.0, 2.0, 3.0]
    assert calls == [{"model": "emb", "input": "hola mundo", "encoding_format": "float"}]


def test_course_variable_names_are_accepted_as_aliases(no_dotenv):
    for name, value in {"QDRANT_URL": "https://q", "LLM_API_KEY": "k", "LLM_API_URL": "https://proxy.example/v1",
                        "LLM_MODEL": "otro-chat", "EMBEDDING_MODEL": "otro-embedding"}.items():
        no_dotenv.setenv(name, value)
    settings = rag_config.load_settings()
    assert settings.llm_base_url == "https://proxy.example/v1"
    assert settings.embedding_base_url == "https://proxy.example/v1"  # hereda la URL común
    assert settings.generation_model == "otro-chat" and settings.embedding_model == "otro-embedding"
    no_dotenv.setenv("GENERATION_MODEL", "prioritario")  # GENERATION_MODEL gana sobre LLM_MODEL
    assert rag_config.load_settings().generation_model == "prioritario"


def test_min_score_can_be_overridden_from_the_environment(no_dotenv):
    for name, value in {"QDRANT_URL": "https://q", "LLM_API_KEY": "k", "EMBEDDING_MODEL": "emb",
                        "GENERATION_MODEL": "gen", "RAG_MIN_SCORE": "0.42"}.items():
        no_dotenv.setenv(name, value)
    assert rag_config.load_settings().min_score == pytest.approx(0.42)
    no_dotenv.setenv("RAG_MIN_SCORE", "mucho")
    with pytest.raises(rag_config.RagConfigError, match="RAG_MIN_SCORE"):
        rag_config.load_settings()


def test_importing_the_pipeline_does_not_need_any_credentials(no_dotenv):
    """Los clientes son perezosos: sin .env ni claves, solo falla al intentar usarlos (no al importar)."""
    with pytest.raises(rag_config.RagConfigError):
        process.embed("hola")


# --------------------------------------------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def all_chunks() -> list[process.Chunk]:
    return process.build_chunks(DOCS_DIR)


def chunks_of(all_chunks, slug):
    return [c for c in all_chunks if c.source_document == slug]


@pytest.mark.parametrize("slug", rag_config.SOURCE_DOCUMENTS)
def test_each_document_yields_at_least_three_chunks_but_not_one_per_line(all_chunks, slug):
    doc_lines = [line for line in (DOCS_DIR / f"brasaland-{slug}.es.md").read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    produced = chunks_of(all_chunks, slug)
    assert 3 <= len(produced) < len(doc_lines)


def test_all_four_source_documents_are_indexed(all_chunks):
    assert {c.source_document for c in all_chunks} == {"loyalty-program", "waste-protocol", "menu-allergens",
                                                       "supplier-ordering"}


def test_payload_has_exactly_the_briefing_fields_and_values(all_chunks):
    for chunk in all_chunks:
        payload = chunk.payload()
        assert set(payload) == BRIEFING_PAYLOAD_FIELDS
        assert payload["company"] == "brasaland" and payload["language"] == "es"
        assert payload["section"].strip() and payload["text"].strip()


def test_chunk_indexes_are_sequential_per_document(all_chunks):
    for slug in rag_config.SOURCE_DOCUMENTS:
        assert [c.chunk_index for c in chunks_of(all_chunks, slug)] == list(range(len(chunks_of(all_chunks, slug))))


def test_point_ids_are_unique_valid_uuids_and_deterministic(all_chunks):
    ids = [c.point_id for c in all_chunks]
    assert len(set(ids)) == len(ids)
    assert ids == [c.point_id for c in process.build_chunks(DOCS_DIR)]
    import uuid
    assert all(str(uuid.UUID(i)) == i for i in ids)


def test_no_chunk_is_cut_in_the_middle_of_a_sentence(all_chunks):
    for chunk in all_chunks:
        assert chunk.text.rstrip()[-1] in ".?!)", f"{chunk.source_document}#{chunk.chunk_index} termina a medias"
        assert chunk.text[0].isupper() or chunk.text[0] in "¿¡-", f"{chunk.source_document}#{chunk.chunk_index}"


@pytest.mark.parametrize(
    "slug, fragments",
    [
        ("loyalty-program", ["Oro (50+ puntos)", "15% de descuento permanente"]),  # nivel y su beneficio juntos
        ("loyalty-program", ["Cada 5 puntos redimidos", "20.000 COP (20 USD)"]),
        ("waste-protocol", ["2 kg de proteína cárnica", "nota explicativa obligatoria"]),
        ("waste-protocol", ["superior a 5 kg en una semana", "Tres semanas consecutivas"]),
        ("menu-allergens", ["Costillas BBQ Brasaland", "trazas de maní"]),
        ("menu-allergens", ["Nunca se garantiza", "cero riesgo de contaminación cruzada"]),
        ("supplier-ordering", ["recargo del 8%", "aprobación de Lucía Fernández", "500 USD"]),
        ("supplier-ordering", ["Vegetales y frutas", "lunes y jueves", "entrega en 24 horas"]),
    ],
)
def test_a_rule_and_its_condition_always_live_in_the_same_chunk(all_chunks, slug, fragments):
    assert any(all(fragment in chunk.text for fragment in fragments) for chunk in chunks_of(all_chunks, slug))


def test_oversized_lists_are_split_between_items_repeating_the_lead_in(monkeypatch):
    monkeypatch.setattr(process, "MAX_CHARS", 120)
    items = [f"- Regla número {n}: hacer la tarea {n} con cuidado y registrarla." for n in range(1, 7)]
    text = "# Doc\n\nReglas del procedimiento:\n" + "\n".join(items) + "\n"
    document = process.SourceDocument("waste-protocol", "Doc", text, Path("brasaland-waste-protocol.es.md"))
    chunks = process.chunk_document(document)
    assert len(chunks) > 1
    assert all(c.text.startswith("Reglas del procedimiento:") for c in chunks)
    assert [line for c in chunks for line in c.text.splitlines() if line.startswith("- ")] == items  # ningún ítem partido


def test_oversized_paragraphs_are_split_at_sentence_boundaries(monkeypatch):
    monkeypatch.setattr(process, "MAX_CHARS", 90)
    text = "# Doc\n\nPrimera frase completa y larga. Segunda frase completa y larga. Tercera frase completa y larga.\n"
    document = process.SourceDocument("waste-protocol", "Doc", text, Path("brasaland-waste-protocol.es.md"))
    chunks = process.chunk_document(document)
    assert len(chunks) >= 2
    assert all(c.text.endswith(".") for c in chunks)


def test_markdown_headings_become_section_names():
    text = "# Doc\n\n## Reglas\n\nPrimera regla completa.\n\n## Excepciones\n\nUna excepción completa.\n"
    document = process.SourceDocument("waste-protocol", "Doc", text, Path("brasaland-waste-protocol.es.md"))
    assert [c.section for c in process.chunk_document(document)] == ["Reglas", "Excepciones"]


def test_missing_source_documents_raise_a_clear_error(tmp_path):
    for path in list(DOCS_DIR.glob("*.md"))[:3]:
        shutil.copy(path, tmp_path / path.name)
    with pytest.raises(process.KnowledgeBaseError, match="Faltan documentos fuente"):
        process.load_documents(tmp_path)
    with pytest.raises(process.KnowledgeBaseError):
        process.load_documents(tmp_path / "no-existe")


def test_embed_rejects_empty_text():
    with pytest.raises(ValueError):
        process.embed("   ")


# --------------------------------------------------------------------------------------------------------------
# setup() con Qdrant en memoria
# --------------------------------------------------------------------------------------------------------------
def all_points(client: QdrantClient):
    points, _ = client.scroll("brasaland_knowledge", limit=1000, with_payload=True, with_vectors=True)
    return points


def test_setup_creates_the_brasaland_collection_with_every_chunk(memory_client, all_chunks):
    summary = process.setup(client=memory_client, embed_fn=fake_embed)
    points = all_points(memory_client)
    assert summary["collection"] == "brasaland_knowledge"
    assert summary["chunks"] == len(all_chunks) == len(points)
    assert summary["vector_size"] == 128
    assert sum(summary["per_document"].values()) == len(all_chunks)
    assert all(set(p.payload) == BRIEFING_PAYLOAD_FIELDS for p in points)
    assert all(len(p.vector) == 128 for p in points)


def test_setup_stores_the_embedding_of_the_chunk_text(memory_client, all_chunks):
    process.setup(client=memory_client, embed_fn=fake_embed)
    by_id = {str(p.id): p for p in all_points(memory_client)}
    first = all_chunks[0]
    expected = fake_embed(first.embedding_text)
    norm = sum(v * v for v in expected) ** 0.5
    stored = by_id[first.point_id].vector
    assert stored == pytest.approx([v / norm for v in expected], rel=1e-4)  # Qdrant normaliza para coseno
    assert by_id[first.point_id].payload["text"] == first.text


def test_setup_is_idempotent(memory_client):
    first = process.setup(client=memory_client, embed_fn=fake_embed)
    ids_after_first = sorted(str(p.id) for p in all_points(memory_client))
    second = process.setup(client=memory_client, embed_fn=fake_embed)
    ids_after_second = sorted(str(p.id) for p in all_points(memory_client))
    assert first["chunks"] == second["chunks"] == len(ids_after_second)
    assert ids_after_first == ids_after_second  # mismos puntos, ninguno duplicado
    assert second["stale_points_removed"] == 0


def test_setup_removes_points_that_no_longer_exist_in_the_documents(memory_client, tmp_path):
    process.setup(client=memory_client, embed_fn=fake_embed)
    before = len(all_points(memory_client))
    for path in DOCS_DIR.glob("*.md"):
        shutil.copy(path, tmp_path / path.name)
    shortened = tmp_path / "brasaland-supplier-ordering.es.md"
    shortened.write_text(shortened.read_text(encoding="utf-8").split("Regla de stock mínimo")[0], encoding="utf-8")
    summary = process.setup(tmp_path, client=memory_client, embed_fn=fake_embed)
    assert summary["stale_points_removed"] >= 1
    assert len(all_points(memory_client)) == before - summary["stale_points_removed"]


def test_setup_recreates_the_collection_when_the_vector_size_changes(memory_client):
    process.setup(client=memory_client, embed_fn=lambda text: fake_embed(text, dim=64))
    summary = process.setup(client=memory_client, embed_fn=lambda text: fake_embed(text, dim=32))
    assert summary["vector_size"] == 32
    assert all(len(p.vector) == 32 for p in all_points(memory_client))


# --------------------------------------------------------------------------------------------------------------
# Preguntas de evaluación y funciones puras de la evaluación
# --------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def queries() -> list[dict]:
    return json.loads(QUERIES_PATH.read_text(encoding="utf-8"))


def test_the_eval_file_has_at_least_eight_questions_covering_every_source_document(queries):
    answerable = [q for q in queries if q["type"] == "answerable"]
    assert len(answerable) >= 8
    assert {q["expected_source_document"] for q in answerable} == set(rag_config.SOURCE_DOCUMENTS)
    assert len({q["id"] for q in queries}) == len(queries)
    assert any(q["type"] in {"off_topic", "unanswerable"} for q in queries)
    assert all(q["question"].strip() and q["expected_answer"].strip() for q in queries)


def test_every_expected_chunk_in_the_eval_file_really_exists(queries, all_chunks):
    existing = {(c.source_document, c.section) for c in all_chunks}
    for q in queries:
        if q["type"] == "answerable":
            assert (q["expected_source_document"], q["expected_section"]) in existing, q["id"]


def test_recall_and_rank_helpers():
    scored = [SimpleNamespace(score=0.9, payload={"source_document": "a", "section": "x"}),
              SimpleNamespace(score=0.8, payload={"source_document": "b", "section": "y"})]
    assert evaluate_rag.expected_rank(scored, "b", "y") == 2
    assert evaluate_rag.expected_rank(scored, "c", "z") is None
    assert evaluate_rag.recall_at_k([1, 2, 3, 4, None], k=3) == pytest.approx(0.6)
    assert evaluate_rag.recall_at_k([]) == 0.0


def test_numeric_tokens_normalize_thousand_separators_and_ignore_list_markers():
    assert evaluate_rag.numeric_tokens("20.000 COP (20 USD)") == {"20000", "20"}
    assert evaluate_rag.numeric_tokens("10000 COP") == evaluate_rag.numeric_tokens("10.000 COP")
    assert evaluate_rag.numeric_tokens("1. Primero\n2. Segundo\nTotal 3%") == {"3"}


def test_faithfulness_flags_numbers_that_are_not_in_the_retrieved_context():
    context = ["Oro (50+ puntos): 15% de descuento permanente."]
    assert evaluate_rag.unsupported_numbers("Con 50 puntos tienes 15% de descuento.", context) == []
    assert evaluate_rag.unsupported_numbers("Tienes 30% de descuento con 50 puntos.", context) == ["30"]


def test_honesty_and_allergen_phrase_checks():
    assert evaluate_rag.says_no_information("No tengo información suficiente para responder eso.")
    assert not evaluate_rag.says_no_information("El nivel Oro es desde 50 puntos.")
    assert evaluate_rag.forbidden_allergen_phrases("Es un plato sin riesgo para ti.") == ["sin riesgo"]
    assert evaluate_rag.forbidden_allergen_phrases("Nunca se garantiza cero riesgo.") == []


def test_threshold_recommendation_is_the_midpoint_when_scores_are_separable():
    result = evaluate_rag.recommend_threshold([0.6, 0.7, 0.5], [0.2, 0.3])
    assert result["separable"] is True and result["min_score"] == pytest.approx(0.4)


def test_threshold_recommendation_warns_when_scores_overlap():
    result = evaluate_rag.recommend_threshold([0.5, 0.6], [0.55])
    assert result["separable"] is False and result["min_score"] < 0.5
    with pytest.raises(ValueError):
        evaluate_rag.recommend_threshold([], [0.2])


def test_retrieval_and_answer_evaluation_run_on_an_in_memory_index(indexed_client, queries):
    retrieval = evaluate_rag.run_retrieval_eval(queries, client=indexed_client, embed_fn=fake_embed)
    assert 0.0 <= retrieval["recall_at_3"] <= 1.0
    assert len(retrieval["rows"]) == len(queries)

    answers = evaluate_rag.run_answer_eval(
        queries, min_score=0.2, client=indexed_client, embed_fn=fake_embed,
        complete_fn=lambda messages: "No tengo información suficiente para responder eso.",
    )
    assert len(answers["rows"]) == len(queries)
    assert answers["faithful"] and answers["honest_when_unknown"]


def test_evaluation_uses_the_configured_threshold_by_default(monkeypatch):
    monkeypatch.delenv("RAG_MIN_SCORE", raising=False)
    monkeypatch.setattr(rag_config, "load_settings", lambda: (_ for _ in ()).throw(rag_config.RagConfigError("x")))
    assert evaluate_rag.configured_min_score() == rag_config.DEFAULT_MIN_SCORE == 0.45
    monkeypatch.setattr(rag_config, "load_settings", lambda: SimpleNamespace(min_score=0.5))
    assert evaluate_rag.configured_min_score() == 0.5
