# Carpeta `data/eval`

Esta carpeta está orientada a **evaluación y validación**: datasets de evaluación, “golden sets”, resultados de experimentos, métricas, y artefactos usados para medir calidad de modelos, RAG, agentes o pipelines.

- **Propósito principal**: centralizar los insumos y salidas de evaluación para asegurar mejoras medibles a lo largo de los hitos del proyecto.
- **Recomendación**: documenta cada set de evaluación (qué mide, cómo se construyó, criterios de éxito) y evita incluir datos sensibles; si es necesario, usa datos sintéticos o anonimizados.

## Evaluación del modelo (`evaluation_report.md`, `evaluation_metrics.json`, `learning_curve.png`)

Evaluación técnica del modelo de ventas (`scripts/evaluate_sales_model.py`, solo con los meses de entrenamiento):
validación cruzada temporal (5 folds, media ± desviación), MAE y RMSE de entrenamiento y validación, curva de
aprendizaje, diagnóstico (bien ajustado / underfitting / overfitting) y acción correctiva. Se regenera con
`uv run python scripts/evaluate_sales_model.py`; el reporte escrito es `evaluation_report.md`.

## `sales_forecast/`

Resultados del modelo de predicción de ventas (`scripts/train_sales_forecast.py`): `metrics.json` (MSE, PSI, Gini,
K2 Score, validación y huella del dataset), `predictions.csv`, `forecast.png` y la descomposición en tendencia, estacionalidad y residuo de los meses de
entrenamiento (`decomposition.csv`, `decomposition.png`). Se regeneran con
`uv run python scripts/train_sales_forecast.py`; la explicación está en `scripts/sales_forecast/README.es.md`.
