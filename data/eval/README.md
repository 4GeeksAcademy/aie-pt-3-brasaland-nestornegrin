# `data/eval` folder

This folder is for **evaluation and validation**: evaluation datasets, golden sets, experiment results, metrics, and artifacts used to measure quality for models, RAG, agents, or pipelines.

- **Main purpose**: centralize evaluation inputs and outputs so improvements stay measurable across project milestones.
- **Recommendation**: document each evaluation set (what it measures, how it was built, success criteria) and avoid sensitive data; use synthetic or anonymized data when needed.

> _Spanish version: [README.es.md](./README.es.md)._

## `sales_forecast/`

Output of the sales forecast model (`scripts/train_sales_forecast.py`): `metrics.json` (MSE, PSI, Gini, K2 Score,
validation, dataset fingerprint), `predictions.csv` and `forecast.png`. Regenerate with
`uv run python scripts/train_sales_forecast.py`; see `scripts/sales_forecast/README.es.md` for the explanation.
