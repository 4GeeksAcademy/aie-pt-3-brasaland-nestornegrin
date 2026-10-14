# `data/pipelines` folder

This folder groups **all data pipelines in the monorepo** related to the company: ingestion, ETL/ELT, cleaning, transformation, and loading into analytical or production systems.

Each subfolder or file under `data/pipelines/` should represent **one pipeline or job set** (for example `sales-etl`, `telemetry-stream`, `customer-segmentation`) and include the required configuration (scripts, orchestration, connectors, schemas, etc.).

- **Main purpose**: consolidate in one place the data movement and transformation logic that powers the company’s applications and analytics.
- **Recommendation**: document pipelines as you add them—their goal, data sources and sinks, dependencies, and how to run them in development, testing, and production.


## Current pipelines

### `pipeline.py` — Inventory Performance by Restaurant

Prefect flow with three subflows (extract → transform → load) that turns `telemetry_events` into the K1–K6 KPIs in `reporting.restaurant_inventory_daily`. Full design in [`PIPELINE_DESIGN.md`](./PIPELINE_DESIGN.md) (Spanish).

```bash
python data/pipelines/pipeline.py                                              # single run (incremental)
python data/pipelines/pipeline.py --date-from 2026-10-01 --date-to 2026-10-07  # recompute a range
python data/pipelines/pipeline.py --serve                                      # scheduled: every day 10:00 UTC
python -m pytest tests/pipelines/test_pipeline.py                              # unit tests (no database)
```

Requires `DATABASE_URL` (in `.env` or `services/api/.env`). Results are shown in the `/reporting` dashboard of `uis/backoffice/`.

> _Spanish version: [README.es.md](./README.es.md)._
