# `scripts` folder

This folder contains **helper scripts** for the monorepo: development automation, maintenance utilities, repetitive tasks (setup, lint, migrations, data generation, etc.), and internal tooling.

- **Main purpose**: group support tools that do not belong to a specific app, agent, or pipeline but make the team’s work easier.
- **Recommendation**: document each script (what it does, parameters, requirements, usage examples) and keep them reproducible (and safe) across environments.

> _Spanish version: [README.es.md](./README.es.md)._

## Nightly telemetry script (`nightly_export.py`)

Exports yesterday's (UTC) `telemetry_events` to CSV, launches the data pipeline as a subprocess and records what happened in
the `job_runs` table. It is a **process fully independent from the API** (it does not import FastAPI).

```bash
python scripts/nightly_export.py                         # yesterday (UTC)
TARGET_DATE=2026-10-14 python scripts/nightly_export.py  # a specific day, no code change
```

- **States** (`services/job_runner/`): `pending → processing → completed | failed`. `processing` IS the lock: if another
  instance is `processing`, this one aborts silently. If a `completed` row already exists for that `target_date`, nothing is repeated.
- **Output:** `data/raw/telemetry_YYYY-MM-DD.csv` (only if it does not exist; backup/audit — the pipeline reads from the DB).
- **Exit codes:** 0 completed or skipped · 1 failed · 2 invalid configuration (`TARGET_DATE`, no DB).
- **Trigger:** crontab, see [`infra/cron/`](../infra/cron/README.md).
- **Tests:** `python -m pytest tests/jobs`.

## Sales forecast model

`train_sales_forecast.py` trains and evaluates a regression model (Random Forest or XGBoost) on
`data/raw/brasaland_sales.csv`: 8-year / 2-year split, MSE, PSI, Gini, K2 Score and a forecast chart with its
variability range, plus a trend / seasonality / residual decomposition (STL) of the training months. Code lives in `scripts/sales_forecast/`; model choice and metrics are explained in
`scripts/sales_forecast/README.es.md`.
`evaluate_sales_model.py` evaluates that model (training months only): 5-fold `TimeSeriesSplit` with an explicit
chronological-order check, MAE / RMSE as mean ± std, a learning curve and a bias-variance diagnosis; results in
`data/eval/evaluation_report.md`.

```bash
uv run python scripts/train_sales_forecast.py
uv run pytest tests/pipelines -v
```
