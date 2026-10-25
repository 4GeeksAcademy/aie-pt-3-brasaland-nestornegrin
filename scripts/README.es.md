# Carpeta `scripts`

Esta carpeta contiene **scripts auxiliares** del monorepo: automatizaciones de desarrollo, utilidades de mantenimiento, tareas repetitivas (setup, lint, migraciones, generación de datos, etc.) y tooling interno.

- **Propósito principal**: agrupar herramientas de soporte que no pertenecen a una app/agente/pipeline específico, pero facilitan el trabajo del equipo.
- **Recomendación**: documenta cada script (qué hace, parámetros, requisitos, ejemplos de uso) y procura que sean reproducibles (y seguros) en distintos entornos.

## Análisis de incidencias

`analyze.py` valida y resume CSV de incidencias sin enviar el contenido a
servicios externos. Usa la misma lógica que la API y excluye de las métricas
los registros inválidos, pero muestra todos sus motivos.

```bash
python3 scripts/analyze.py data/raw/incidents-COMPANY.csv
```

Responde `s` al final para escribir `results.csv`. Para cambiar la ruta de
salida usa `--output ruta/resultados.csv`.

## Modelo de predicción de ventas

`train_sales_forecast.py` entrena y evalúa un modelo de regresión (Random Forest o XGBoost) sobre
`data/raw/brasaland_sales.csv`: split 8 años / 2 años, MSE, PSI, Gini, K2 Score y gráfica con rango de variabilidad.
El código vive en `scripts/sales_forecast/` y su criterio de elección y métricas están explicados en
`scripts/sales_forecast/README.es.md`.

```bash
uv run python scripts/train_sales_forecast.py
uv run pytest tests/pipelines -v
```
