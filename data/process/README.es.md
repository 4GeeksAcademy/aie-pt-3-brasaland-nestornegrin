# Carpeta `data/process`

Esta carpeta contiene **datos procesados/intermedios** y/o artefactos derivados de los pipelines (por ejemplo: datasets limpios, features, agregados, tablas intermedias o resultados de transformaciones).

- **Propósito principal**: separar claramente los datos “raw” de los datos listos para análisis/modelado/consumo por apps.
- **Recomendación**: documenta qué pipeline genera cada artefacto, su esquema, periodicidad, y cómo se valida su calidad (checks, constraints, tests de datos).

## RAG — chunking e indexación (`rag.py`, `rag_config.py`)

Hito 7: `rag.py` lee los documentos de `docs/company-knowledge-base/`, los divide en chunks semánticos, genera los
embeddings (`embed()`) e indexa todo en la colección de Qdrant `brasaland_knowledge` (`setup()`, idempotente).
`rag_config.py` concentra la configuración (variables de entorno) y los clientes, que se crean de forma perezosa.
Ejecución: `uv run python -m data.process.rag`. Diseño completo en `docs/rag/rag-design.md`.
