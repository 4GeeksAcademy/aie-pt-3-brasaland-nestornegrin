# Carpeta `data/pipelines`

Esta carpeta agrupa **todos los pipelines de datos del monorepo** relacionados con la compañía: procesos de ingesta, ETL/ELT, limpieza, transformación y carga hacia sistemas analíticos o de producción.

Cada subcarpeta o archivo dentro de `data/pipelines/` debe representar **un pipeline o conjunto de jobs** (por ejemplo `sales-etl`, `telemetry-stream`, `customer-segmentation`) e incluir la configuración necesaria (scripts, orquestación, conectores, esquemas, etc.).

- **Propósito principal**: unificar en un único lugar la lógica de movimiento y transformación de datos que soporta las aplicaciones y analíticas de la compañía.
- **Recomendación**: documenta aquí los pipelines que vayas añadiendo, describiendo su objetivo, orígenes/destinos de datos, dependencias y cómo ejecutarlos en desarrollo, pruebas y producción.

## Pipelines actuales

### `pipeline.py` — Desempeño de Inventario por Restaurante

Flow de Prefect con tres subflows (extracción → transformación → carga) que convierte `telemetry_events` en los KPIs K1–K6 de `reporting.restaurant_inventory_daily`. Diseño completo en [`PIPELINE_DESIGN.md`](./PIPELINE_DESIGN.md).

```bash
python data/pipelines/pipeline.py                                              # corrida única (incremental)
python data/pipelines/pipeline.py --date-from 2026-10-01 --date-to 2026-10-07  # recalcula un rango
python data/pipelines/pipeline.py --serve                                      # programado: todos los días 10:00 UTC
python -m pytest tests/pipelines/test_pipeline.py                              # tests unitarios (sin base de datos)
```

Requiere `DATABASE_URL` (en `.env` o `services/api/.env`). El resultado se ve en el dashboard `/reporting` de `uis/backoffice/`.
