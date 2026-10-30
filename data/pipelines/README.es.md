# Carpeta `data/pipelines`

Esta carpeta agrupa **todos los pipelines de datos del monorepo** relacionados con la compañía: procesos de ingesta, ETL/ELT, limpieza, transformación y carga hacia sistemas analíticos o de producción.

Cada subcarpeta o archivo dentro de `data/pipelines/` debe representar **un pipeline o conjunto de jobs** (por ejemplo `sales-etl`, `telemetry-stream`, `customer-segmentation`) e incluir la configuración necesaria (scripts, orquestación, conectores, esquemas, etc.).

- **Propósito principal**: unificar en un único lugar la lógica de movimiento y transformación de datos que soporta las aplicaciones y analíticas de la compañía.
- **Recomendación**: documenta aquí los pipelines que vayas añadiendo, describiendo su objetivo, orígenes/destinos de datos, dependencias y cómo ejecutarlos en desarrollo, pruebas y producción.

## RAG — recuperación y generación (`rag.py`)

Hito 7: `retrieve()` busca en Qdrant y descarta lo que no llega a `min_score`; `generate_answer()` arma el prompt con la
voz y audiencia del BRIEFING y llama al LLM de generación; `query()` es `retrieve()` + `generate_answer()` y es lo único
que llaman los consumidores externos (el endpoint `POST /knowledge/query`). Diseño en `docs/rag/rag-design.md`.
