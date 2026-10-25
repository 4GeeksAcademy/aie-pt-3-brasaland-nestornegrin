"""Entrena y evalúa el modelo de predicción de ventas de Brasaland (ticket: modelo de regresión).

Uso, desde la raíz del monorepo:

    uv run python scripts/train_sales_forecast.py

Flujo:
 1. Carga y valida `data/raw/brasaland_sales.csv` (el original del curso, sin modificar).
 2. Divide por fecha: primeros 8 años -> entrenamiento, 2 años más recientes -> prueba.
 3. Elige entre Random Forest y XGBoost con validación walk-forward DENTRO del entrenamiento (la prueba no se usa).
 4. Entrena el elegido con el entrenamiento y lo evalúa sobre la prueba: MSE, PSI, Gini y K2 Score (R²).
 5. Guarda `metrics.json`, `predictions.csv` y `forecast.png` en `data/eval/sales_forecast/`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
import xgboost

if __package__ in (None, ""):  # permite `python scripts/train_sales_forecast.py` desde la raíz
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sales_forecast import metrics  # noqa: E402
from scripts.sales_forecast.data import (  # noqa: E402
    DEFAULT_DATA_PATH,
    REPO_ROOT,
    TARGET,
    TEST_YEARS,
    TRAIN_YEARS,
    file_sha256,
    load_sales,
    split_train_test,
)
from scripts.sales_forecast.features import build_training_frame  # noqa: E402
from scripts.sales_forecast.model import (  # noqa: E402
    MODEL_NAMES,
    RANDOM_STATE,
    fit_model,
    one_step_forecast,
    prediction_band,
    recursive_forecast,
    walk_forward_cv,
)
from scripts.sales_forecast.plot import plot_forecast  # noqa: E402

DEFAULT_OUT_DIR = REPO_ROOT / "data" / "eval" / "sales_forecast"
COVERAGE = 0.80
# Regla de elección fijada ANTES de mirar la prueba: XGBoost solo se prefiere si mejora el RMSE de validación en más
# de este margen; si no, la diferencia es ruido y gana el modelo más simple y explicable (Random Forest).
XGBOOST_MIN_IMPROVEMENT = 0.05


def choose_model(results: dict) -> tuple[str, str]:
    forest, boosted = results["random_forest"].mean_rmse, results["xgboost"].mean_rmse
    gain = (forest - boosted) / forest
    if gain > XGBOOST_MIN_IMPROVEMENT:
        return "xgboost", (
            f"XGBoost reduce el RMSE de validación un {gain:.1%} (más del {XGBOOST_MIN_IMPROVEMENT:.0%} exigido): "
            "la mejora de precisión justifica su mayor complejidad."
        )
    return "random_forest", (
        f"Diferencia de RMSE de validación entre algoritmos: {gain:+.1%} a favor de XGBoost, por debajo del "
        f"{XGBOOST_MIN_IMPROVEMENT:.0%} exigido. Con solo 84 filas útiles es un empate técnico, así que se elige "
        "Random Forest: más simple de explicar a Finanzas, menos hiperparámetros y menos riesgo de sobreajuste."
    )


def run(data_path: Path, out_dir: Path, forced_model: str | None = None) -> dict:
    data = load_sales(data_path)
    train, test = split_train_test(data)
    train_series, test_series, full_series = train[TARGET], test[TARGET], data[TARGET]

    # --- Elección del algoritmo: solo con datos de entrenamiento ---
    cv = {name: walk_forward_cv(name, train_series) for name in MODEL_NAMES}
    chosen, reason = choose_model(cv)
    if forced_model:
        chosen, reason = forced_model, f"Forzado por el usuario con --model {forced_model}."

    # --- Entrenamiento (solo meses de entrenamiento) y predicción ---
    model = fit_model(chosen, train_series)
    recursive = recursive_forecast(model, train_series, horizon=len(test_series))
    one_step = one_step_forecast(model, full_series, test_series.index)
    low, high = prediction_band(recursive, cv[chosen].rel_errors, COVERAGE)

    # --- Métricas SOBRE EL CONJUNTO DE PRUEBA ---
    def block(forecast: pd.Series) -> dict:
        return {
            "mse_usd2": metrics.mse(test_series, forecast),
            "rmse_usd": metrics.rmse(test_series, forecast),
            "mape_pct": metrics.mape(test_series, forecast),
            "gini_normalized": metrics.normalized_gini(test_series, forecast),
            "k2_score_r2": metrics.k2_score(test_series, forecast),
        }

    test_ratio = build_training_frame(full_series)[1].loc[test_series.index]
    train_ratio = build_training_frame(train_series)[1]
    psi_bins = 5  # quintiles: con solo 24 meses de prueba, 10 tramos dejarían tramos vacíos y distorsionarían el índice
    psi_revenue = metrics.psi(train_series, test_series, bins=psi_bins)
    psi_ratio = metrics.psi(train_ratio, test_ratio, bins=psi_bins)
    noise_revenue = metrics.psi_noise_threshold(train_series, test_series, bins=psi_bins)
    noise_ratio = metrics.psi_noise_threshold(train_ratio, test_ratio, bins=psi_bins)
    naive = full_series.shift(12).loc[test_series.index]  # referencia: "lo mismo que el mismo mes del año pasado"

    results = {
        "dataset": {
            "path": str(Path(data_path).relative_to(REPO_ROOT)) if Path(data_path).is_absolute() and REPO_ROOT in Path(data_path).parents else str(data_path),
            "sha256": file_sha256(data_path),
            "rows": int(len(data)),
        },
        "split": {
            "rule": f"primeros {TRAIN_YEARS} años = entrenamiento, {TEST_YEARS} años más recientes = prueba",
            "train": [train.index.min().strftime("%Y-%m"), train.index.max().strftime("%Y-%m"), int(len(train))],
            "test": [test.index.min().strftime("%Y-%m"), test.index.max().strftime("%Y-%m"), int(len(test))],
            "effective_training_rows": int(len(train_ratio)),
        },
        "reproducibility": {"random_state": RANDOM_STATE, "sklearn": sklearn.__version__, "xgboost": xgboost.__version__, "numpy": np.__version__, "pandas": pd.__version__},
        "model_selection": {
            "method": "validación walk-forward en los últimos 3 años de ENTRENAMIENTO (pronóstico recursivo de 12 meses)",
            "validation": {
                name: {"mean_rmse_usd": result.mean_rmse, "mean_mape_pct": result.mean_mape, "folds": result.folds}
                for name, result in cv.items()
            },
            "chosen": chosen,
            "reason": reason,
        },
        "test_metrics": {
            "primary_recursive_24_months": block(recursive),
            "one_step_ahead": block(one_step),
            "baseline_same_month_last_year": {"mape_pct": metrics.mape(test_series, naive), "rmse_usd": metrics.rmse(test_series, naive)},
        },
        "psi": {
            "bins": psi_bins,
            "revenue_train_vs_test": {"value": psi_revenue, "noise_threshold_p95": noise_revenue, "reading": metrics.psi_reading(psi_revenue, noise_revenue)},
            "revenue_to_level_ratio_train_vs_test": {"value": psi_ratio, "noise_threshold_p95": noise_ratio, "reading": metrics.psi_reading(psi_ratio, noise_ratio)},
        },
        "interval": {
            "coverage_target": COVERAGE,
            "coverage_observed_test": float(((test_series >= low) & (test_series <= high)).mean()),
            "relative_margin_low": float((low / recursive - 1).iloc[0]),
            "relative_margin_high": float((high / recursive - 1).iloc[0]),
        },
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pd.DataFrame(
        {"actual_usd": test_series, "predicted_recursive_usd": recursive, "range_low_usd": low, "range_high_usd": high, "predicted_one_step_usd": one_step}
    ).round(2).to_csv(out_dir / "predictions.csv", index_label="month")
    label = "Random Forest" if chosen == "random_forest" else "XGBoost"
    plot_forecast(train_series, test_series, recursive, low, high, one_step, label, f"{COVERAGE:.0%}", out_dir / "forecast.png")
    return results


def print_summary(results: dict) -> None:
    sel, test = results["model_selection"], results["test_metrics"]
    print(f"Dataset: {results['dataset']['rows']} filas | sha256 {results['dataset']['sha256'][:16]}…")
    print(f"Split: entrenamiento {results['split']['train']} | prueba {results['split']['test']}")
    for name, value in sel["validation"].items():
        print(f"  validación {name:14s} RMSE medio ${value['mean_rmse_usd']:,.0f} | MAPE medio {value['mean_mape_pct']:.2f} %")
    print(f"Modelo elegido: {sel['chosen']}\n  {sel['reason']}")
    for key, title in (("primary_recursive_24_months", "PRINCIPAL (recursivo 24 meses)"), ("one_step_ahead", "un mes por delante")):
        m = test[key]
        print(f"Prueba · {title}: MSE {m['mse_usd2']:,.0f} USD² (RMSE ${m['rmse_usd']:,.0f}, MAPE {m['mape_pct']:.2f} %) | Gini {m['gini_normalized']:.3f} | K2 (R²) {m['k2_score_r2']:.3f}")
    base = test["baseline_same_month_last_year"]
    print(f"Referencia 'mismo mes del año pasado': MAPE {base['mape_pct']:.2f} %")
    for key, value in results["psi"].items():
        if key != "bins":
            print(f"PSI {key}: {value['value']:.3f} (ruido p95 {value['noise_threshold_p95']:.3f}) -> {value['reading']}")
    print(f"Rango {results['interval']['coverage_target']:.0%}: cobertura observada en prueba {results['interval']['coverage_observed_test']:.0%}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH, help="CSV de ventas (por defecto data/raw/brasaland_sales.csv)")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Carpeta de salida")
    parser.add_argument("--model", choices=MODEL_NAMES, default=None, help="Fuerza un algoritmo en vez de elegirlo por validación")
    args = parser.parse_args()
    print_summary(run(args.data, args.out_dir, args.model))


if __name__ == "__main__":
    main()
