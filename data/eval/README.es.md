# Carpeta `data/eval`

Esta carpeta está orientada a **evaluación y validación**: datasets de evaluación, “golden sets”, resultados de experimentos, métricas, y artefactos usados para medir calidad de modelos, RAG, agentes o pipelines.

- **Propósito principal**: centralizar los insumos y salidas de evaluación para asegurar mejoras medibles a lo largo de los hitos del proyecto.
- **Recomendación**: documenta cada set de evaluación (qué mide, cómo se construyó, criterios de éxito) y evita incluir datos sensibles; si es necesario, usa datos sintéticos o anonimizados.

## `sales_forecast/`

Resultados del modelo de predicción de ventas (`scripts/train_sales_forecast.py`): `metrics.json` (MSE, PSI, Gini,
K2 Score, validación y huella del dataset), `predictions.csv`, `forecast.png` y la descomposición en tendencia, estacionalidad y residuo de los meses de
entrenamiento (`decomposition.csv`, `decomposition.png`). Se regeneran con
`uv run python scripts/train_sales_forecast.py`; la explicación está en `scripts/sales_forecast/README.es.md`.
