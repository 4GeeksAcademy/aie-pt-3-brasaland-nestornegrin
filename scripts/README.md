# `scripts` folder

This folder contains **helper scripts** for the monorepo: development automation, maintenance utilities, repetitive tasks (setup, lint, migrations, data generation, etc.), and internal tooling.

- **Main purpose**: group support tools that do not belong to a specific app, agent, or pipeline but make the team’s work easier.
- **Recommendation**: document each script (what it does, parameters, requirements, usage examples) and keep them reproducible (and safe) across environments.

> _Spanish version: [README.es.md](./README.es.md)._

## Sales forecast model

`train_sales_forecast.py` trains and evaluates a regression model (Random Forest or XGBoost) on
`data/raw/brasaland_sales.csv`: 8-year / 2-year split, MSE, PSI, Gini, K2 Score and a forecast chart with its
variability range. Code lives in `scripts/sales_forecast/`; model choice and metrics are explained in
`scripts/sales_forecast/README.es.md`.

```bash
uv run python scripts/train_sales_forecast.py
uv run pytest tests/pipelines -v
```
