# `data/pipelines` folder

This folder groups **all data pipelines in the monorepo** related to the company: ingestion, ETL/ELT, cleaning, transformation, and loading into analytical or production systems.

Each subfolder or file under `data/pipelines/` should represent **one pipeline or job set** (for example `sales-etl`, `telemetry-stream`, `customer-segmentation`) and include the required configuration (scripts, orchestration, connectors, schemas, etc.).

- **Main purpose**: consolidate in one place the data movement and transformation logic that powers the company’s applications and analytics.
- **Recommendation**: document pipelines as you add them—their goal, data sources and sinks, dependencies, and how to run them in development, testing, and production.

> _Spanish version: [README.es.md](./README.es.md)._

## RAG — retrieval and generation (`rag.py`)

Milestone 7: `retrieve()` searches Qdrant and drops anything below `min_score`; `generate_answer()` builds the prompt
with the BRIEFING's voice and audience and calls the generation LLM; `query()` is `retrieve()` + `generate_answer()`
and is the only function external consumers call (the `POST /knowledge/query` endpoint). Design in
`docs/rag/rag-design.md`.
