"""Evaluación del RAG de Brasaland (Hito 7): Recall@3, calibración del umbral y fidelidad de las respuestas.

Uso (necesita el `.env` con Qdrant y los modelos, y haber ejecutado `setup()` antes):

    uv run python -m scripts.evaluate_rag                  # Recall@3 + umbral recomendado
    uv run python -m scripts.evaluate_rag --answers        # además genera las respuestas y revisa su fidelidad
    uv run python -m scripts.evaluate_rag --min-score 0.4  # fija el umbral en vez de usar el calibrado

Qué mide, con las preguntas de `data/eval/test-queries.json`:

* Recall@3 (KPI del BRIEFING, ≥ 80 %): en cuántas preguntas respondibles el chunk correcto (documento + sección
  esperados) está entre los 3 primeros resultados. Se calcula SIN umbral: mide la calidad de la búsqueda.
* Umbral mínimo de similitud: punto medio entre la puntuación más baja de un chunk correcto y la más alta que
  obtienen las preguntas fuera de tema. Si no hay separación, lo avisa en vez de inventarse un número.
* Fidelidad (con --answers): ningún dato numérico en la respuesta que no aparezca en los chunks recuperados; las
  preguntas sin respuesta en los documentos deben contestarse diciendo que no hay información; nunca "sin riesgo".

Las funciones puras (recall, números, umbral) están separadas del acceso a Qdrant y al LLM para poder probarlas
en `tests/pipelines/test_rag.py` sin servicios externos.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

QUERIES_PATH = REPO_ROOT / "data" / "eval" / "test-queries.json"
RESULTS_PATH = REPO_ROOT / "data" / "eval" / "rag_eval_results.json"
RECALL_TARGET = 0.80  # umbral de Recall@3 del BRIEFING
K_RECALL = 3
K_SEARCH = 5

ANSWERABLE = "answerable"
OFF_TOPIC = "off_topic"
UNANSWERABLE = "unanswerable"

# Frases con las que el modelo admite que no tiene la información (comprobación de la respuesta honesta).
NO_INFO_MARKERS = (
    "no tengo información",
    "no tengo informacion",
    "no hay información",
    "no cuento con información",
    "información suficiente",
    "no tengo datos",
    "no aparece",
    "no está en la base",
)
FORBIDDEN_ALLERGEN_PHRASES = ("sin riesgo", "cero riesgo garantizado", "100% seguro")

_NUMBER = re.compile(r"\d[\d.,]*")
_LIST_MARKER = re.compile(r"(?m)^\s*\d+[.)]\s+")


# --------------------------------------------------------------------------------------------------------------
# Funciones puras
# --------------------------------------------------------------------------------------------------------------
def load_queries(path: Path | str = QUERIES_PATH) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def expected_rank(scored: list, expected_document: str, expected_section: str) -> int | None:
    """Posición (desde 1) del chunk esperado en la lista de resultados, o None si no aparece."""
    for position, item in enumerate(scored, start=1):
        payload = item.payload if hasattr(item, "payload") else item
        if payload.get("source_document") == expected_document and payload.get("section") == expected_section:
            return position
    return None


def recall_at_k(ranks: list[int | None], k: int = K_RECALL) -> float:
    """Fracción de preguntas cuyo chunk correcto está entre los `k` primeros resultados."""
    if not ranks:
        return 0.0
    return sum(1 for rank in ranks if rank is not None and rank <= k) / len(ranks)


def numeric_tokens(text: str) -> set[str]:
    """Números de un texto en forma canónica (sin separadores de miles ni puntuación final). Los marcadores de
    lista ("1. ", "2. ") no cuentan como datos."""
    cleaned = _LIST_MARKER.sub("", text)
    tokens = set()
    for raw in _NUMBER.findall(cleaned):
        token = raw.rstrip(".,")
        if re.fullmatch(r"\d{1,3}([.,]\d{3})+", token):  # 10.000 / 20,000 -> 10000 / 20000
            token = re.sub(r"[.,]", "", token)
        tokens.add(token)
    return tokens


def unsupported_numbers(answer: str, context_texts: list[str]) -> list[str]:
    """Números de la respuesta que NO aparecen en ningún chunk recuperado (violaciones de fidelidad)."""
    allowed: set[str] = set()
    for text in context_texts:
        allowed |= numeric_tokens(text)
    return sorted(numeric_tokens(answer) - allowed)


def says_no_information(answer: str) -> bool:
    lowered = answer.lower()
    return any(marker in lowered for marker in NO_INFO_MARKERS)


def forbidden_allergen_phrases(answer: str) -> list[str]:
    lowered = answer.lower()
    return [phrase for phrase in FORBIDDEN_ALLERGEN_PHRASES if phrase in lowered]


def recommend_threshold(positive_scores: list[float], negative_scores: list[float]) -> dict:
    """Umbral = punto medio entre la peor puntuación de un chunk correcto y la mejor de una pregunta fuera de tema.

    Si ambas distribuciones se solapan no hay umbral limpio: se devuelve `separable=False` y el valor más
    conservador (el más bajo de los positivos), para no perder respuestas correctas."""
    if not positive_scores:
        raise ValueError("Hacen falta puntuaciones de chunks correctos para calibrar el umbral.")
    lowest_positive = min(positive_scores)
    highest_negative = max(negative_scores) if negative_scores else None
    if highest_negative is None:
        return {"min_score": round(lowest_positive - 0.05, 3), "separable": None,
                "lowest_positive": lowest_positive, "highest_negative": None}
    separable = lowest_positive > highest_negative
    value = (lowest_positive + highest_negative) / 2 if separable else lowest_positive - 0.01
    return {
        "min_score": round(value, 3),
        "separable": separable,
        "lowest_positive": round(lowest_positive, 4),
        "highest_negative": round(highest_negative, 4),
    }


# --------------------------------------------------------------------------------------------------------------
# Evaluación contra Qdrant y el LLM
# --------------------------------------------------------------------------------------------------------------
def run_retrieval_eval(queries: list[dict], *, client=None, embed_fn=None) -> dict:
    """Recall@3 y puntuaciones por pregunta (sin umbral)."""
    from data.pipelines.rag import search_scored

    rows = []
    for item in queries:
        scored = search_scored(item["question"], k=K_SEARCH, client=client, embed_fn=embed_fn)
        row = {
            "id": item["id"],
            "type": item["type"],
            "question": item["question"],
            "top_score": round(scored[0].score, 4) if scored else None,
            "top_results": [
                {"source_document": s.payload.get("source_document"), "section": s.payload.get("section"),
                 "score": round(s.score, 4)}
                for s in scored[:K_RECALL]
            ],
        }
        if item["type"] == ANSWERABLE:
            rank = expected_rank(scored, item["expected_source_document"], item["expected_section"])
            row["rank_of_expected"] = rank
            row["score_of_expected"] = round(scored[rank - 1].score, 4) if rank else None
        rows.append(row)

    answerable = [r for r in rows if r["type"] == ANSWERABLE]
    recall = recall_at_k([r["rank_of_expected"] for r in answerable])
    positives = [r["score_of_expected"] for r in answerable if r["score_of_expected"] is not None]
    negatives = [r["top_score"] for r in rows if r["type"] == OFF_TOPIC and r["top_score"] is not None]
    return {
        "recall_at_3": round(recall, 4),
        "recall_target": RECALL_TARGET,
        "recall_ok": recall >= RECALL_TARGET,
        "answerable_questions": len(answerable),
        "threshold": recommend_threshold(positives, negatives) if positives else None,
        "rows": rows,
    }


def run_answer_eval(queries: list[dict], *, min_score: float, client=None, embed_fn=None, complete_fn=None) -> dict:
    """Genera la respuesta de cada pregunta con el umbral dado y revisa fidelidad y honestidad."""
    from data.pipelines.rag import generate_answer, retrieve

    rows = []
    for item in queries:
        context = retrieve(item["question"], k=K_SEARCH, min_score=min_score, client=client, embed_fn=embed_fn)
        answer = generate_answer(item["question"], context, complete_fn=complete_fn)
        row = {
            "id": item["id"],
            "type": item["type"],
            "question": item["question"],
            "chunks_used": [f"{c.get('source_document')} — {c.get('section')}" for c in context],
            "answer": answer,
            "unsupported_numbers": unsupported_numbers(answer, [c.get("text", "") for c in context]),
            "forbidden_phrases": forbidden_allergen_phrases(answer),
        }
        if item["type"] != ANSWERABLE:
            row["admits_no_information"] = says_no_information(answer)
        rows.append(row)
    faithful = all(not r["unsupported_numbers"] for r in rows)
    honest = all(r.get("admits_no_information", True) for r in rows)
    safe = all(not r["forbidden_phrases"] for r in rows)
    return {"min_score": min_score, "faithful": faithful, "honest_when_unknown": honest,
            "no_forbidden_allergen_phrases": safe, "rows": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--answers", action="store_true", help="genera también las respuestas y revisa su fidelidad")
    parser.add_argument("--min-score", type=float, default=None, help="umbral a usar (por defecto, el recomendado)")
    parser.add_argument("--out", type=Path, default=RESULTS_PATH, help="dónde guardar el JSON de resultados")
    args = parser.parse_args(argv)

    queries = load_queries()
    retrieval = run_retrieval_eval(queries)
    result: dict = {"retrieval": retrieval}

    print(f"Recall@3 = {retrieval['recall_at_3']:.0%} (objetivo ≥ {RECALL_TARGET:.0%}) -> "
          f"{'OK' if retrieval['recall_ok'] else 'NO CUMPLE'}")
    for row in retrieval["rows"]:
        extra = f"rango={row.get('rank_of_expected')}" if row["type"] == ANSWERABLE else "sin respuesta esperada"
        print(f"  {row['id']} [{row['type']}] top={row['top_score']} {extra} | {row['question']}")
    threshold = retrieval["threshold"]
    print(f"Umbral recomendado: {threshold}")

    if args.answers:
        chosen = args.min_score if args.min_score is not None else (threshold or {}).get("min_score")
        if chosen is None:
            print("No hay umbral: pasa --min-score.")
            return 2
        answers = run_answer_eval(queries, min_score=chosen)
        result["answers"] = answers
        print(f"\nRespuestas con umbral {chosen}: fieles={answers['faithful']}, "
              f"honestas={answers['honest_when_unknown']}, sin frases prohibidas={answers['no_forbidden_allergen_phrases']}")
        for row in answers["rows"]:
            print(f"\n[{row['id']}] {row['question']}\n  -> {row['answer']}")
            if row["unsupported_numbers"]:
                print(f"  !! números sin respaldo en el contexto: {row['unsupported_numbers']}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nResultados guardados en {args.out.relative_to(REPO_ROOT) if args.out.is_relative_to(REPO_ROOT) else args.out}")
    return 0 if retrieval["recall_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
