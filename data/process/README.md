# `data/process` folder

This folder contains **processed/intermediate data** and/or artifacts produced by pipelines (for example: clean datasets, features, aggregates, intermediate tables, or transformation outputs).

- **Main purpose**: clearly separate “raw” data from data ready for analysis, modeling, or app consumption.
- **Recommendation**: document which pipeline produces each artifact, its schema, refresh cadence, and how quality is validated (checks, constraints, data tests).

> _Spanish version: [README.es.md](./README.es.md)._

## RAG — chunking and indexing (`rag.py`, `rag_config.py`)

Milestone 7: `rag.py` reads the documents in `docs/company-knowledge-base/`, splits them into semantic chunks, creates
the embeddings (`embed()`) and indexes everything in the Qdrant collection `brasaland_knowledge` (`setup()`,
idempotent). `rag_config.py` holds the configuration (environment variables) and the lazily created clients.
Run it with `uv run python -m data.process.rag`. Full design in `docs/rag/rag-design.md`.
