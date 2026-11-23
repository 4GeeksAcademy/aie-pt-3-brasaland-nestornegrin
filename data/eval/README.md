# `data/eval` folder

This folder is for **evaluation and validation**: evaluation datasets, golden sets, experiment results, metrics, and artifacts used to measure quality for models, RAG, agents, or pipelines.

- **Main purpose**: centralize evaluation inputs and outputs so improvements stay measurable across project milestones.
- **Recommendation**: document each evaluation set (what it measures, how it was built, success criteria) and avoid sensitive data; use synthetic or anonymized data when needed.

> _Spanish version: [README.es.md](./README.es.md)._

## Model evaluation (`evaluation_report.md`, `evaluation_metrics.json`, `learning_curve.png`)

Technical evaluation of the sales forecast model (`scripts/evaluate_sales_model.py`, training months only): temporal
cross-validation (5 folds, mean ± std), MAE / RMSE for training and validation, the learning curve, the
well-fitted / underfitting / overfitting diagnosis and the corrective action. Regenerate with
`uv run python scripts/evaluate_sales_model.py`; the written report is `evaluation_report.md` (in Spanish).

## `sales_forecast/`

Output of the sales forecast model (`scripts/train_sales_forecast.py`): `metrics.json` (MSE, PSI, Gini, K2 Score,
validation, dataset fingerprint), `predictions.csv`, `forecast.png`, and the trend / seasonality / residual decomposition of the training months
(`decomposition.csv`, `decomposition.png`). Regenerate with
`uv run python scripts/train_sales_forecast.py`; see `scripts/sales_forecast/README.es.md` for the explanation.

## RAG evaluation (`test-queries.json`, `rag_eval_results.json`)

`test-queries.json` has 16 questions about the four documents in `docs/company-knowledge-base/` (12 answerable with
their expected chunk and answer, 2 off-topic and 2 with no answer in the documents). `scripts/evaluate_rag.py` measures
Recall@3 (BRIEFING target ≥ 80 %), recommends the similarity threshold and, with `--answers`, checks answer
faithfulness. Run it with `uv run python -m scripts.evaluate_rag --answers`.
