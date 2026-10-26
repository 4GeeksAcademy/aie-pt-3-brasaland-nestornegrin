"""Evaluación técnica del modelo de ventas de Brasaland (ticket: evaluación de un modelo de regresión).

Uso, desde la raíz del monorepo:

    uv run python scripts/evaluate_sales_model.py

Flujo (solo con los 96 meses de ENTRENAMIENTO; el conjunto de prueba no se usa):
 1. Carga y valida `data/raw/brasaland_sales.csv` y aparta los 2 años de prueba.
 2. Validación cruzada temporal (TimeSeriesSplit, 5 folds) con comprobación explícita del orden cronológico.
 3. MAE y RMSE de entrenamiento y validación, como media ± desviación estándar entre folds.
 4. Curva de aprendizaje y diagnóstico (bien ajustado / underfitting / overfitting).
 5. Evidencia de la acción correctiva: experimento de regularización, relación del sesgo con el crecimiento
    anual y prueba de una feature de crecimiento.
 6. Guarda `learning_curve.png` y `evaluation_metrics.json` en `data/eval/`.

El reporte escrito está en `data/eval/evaluation_report.md` y cita estas cifras.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
import statsmodels

if __package__ in (None, ""):  # permite `python scripts/evaluate_sales_model.py` desde la raíz
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
from scripts.sales_forecast.evaluation import (  # noqa: E402
    CURVE_STEP,
    N_SPLITS,
    VALIDATION_MONTHS,
    bias_vs_growth,
    cross_validate,
    growth_feature_experiment,
    diagnose,
    learning_curve,
    noise_floor_pct,
    regularization_experiment,
)
from scripts.sales_forecast.model import RANDOM_STATE  # noqa: E402
from scripts.sales_forecast.plot import plot_learning_curve  # noqa: E402

DEFAULT_OUT_DIR = REPO_ROOT / "data" / "eval"


def run(data_path: Path, out_dir: Path) -> dict:
    data = load_sales(data_path)
    train, _ = split_train_test(data)  # el conjunto de prueba se descarta: no entra en la evaluación
    series = train[TARGET]

    cv = cross_validate(series)
    curve = learning_curve(series)
    noise = noise_floor_pct(series)
    diagnosis = diagnose(curve, noise)
    experiment = regularization_experiment(series)
    bias_growth = bias_vs_growth(series, cv)
    growth_experiment = growth_feature_experiment(series)

    results = {
        "dataset": {"path": "data/raw/brasaland_sales.csv", "sha256": file_sha256(data_path), "rows": int(len(data))},
        "scope": f"solo los {len(train)} meses de entrenamiento ({TRAIN_YEARS} años); la prueba ({TEST_YEARS} años) no se usa",
        "model": "random_forest (el elegido en el PR anterior, sin cambios)",
        "reproducibility": {"random_state": RANDOM_STATE, "sklearn": sklearn.__version__, "statsmodels": statsmodels.__version__, "numpy": np.__version__, "pandas": pd.__version__},
        "cross_validation": {
            "method": f"TimeSeriesSplit(n_splits={N_SPLITS}, test_size={VALIDATION_MONTHS}), ventana creciente, sin barajar",
            "order_check": "verify_folds: índices consecutivos, entrenamiento anterior a validación, validaciones sucesivas sin solaparse",
            "std": "desviación estándar muestral (ddof=1) entre los folds",
            **cv,
        },
        "learning_curve": {
            "validation": f"fija: el último año de entrenamiento ({VALIDATION_MONTHS} filas)",
            "step_months": CURVE_STEP,
            "points": curve,
        },
        "diagnosis": diagnosis,
        "regularization_experiment": experiment,
        "bias_vs_growth": bias_growth,
        "growth_feature_experiment": growth_experiment,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "evaluation_metrics.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    plot_learning_curve(curve, noise, "Random Forest", out_dir / "learning_curve.png")
    return results


def print_summary(results: dict) -> None:
    cv = results["cross_validation"]
    print(f"Dataset: {results['dataset']['rows']} filas | sha256 {results['dataset']['sha256'][:16]}… | {results['scope']}")
    print(f"Validación cruzada: {cv['n_splits']} folds ({cv['method']})")
    for fold in cv["folds"]:
        print(
            f"  fold {fold['fold']}: entrena {fold['train_rows']} meses -> valida {fold['validation_window'][0]}..{fold['validation_window'][1]} | "
            f"MAE val {fold['validation']['mae_pct']:.2f} % (${fold['validation']['mae_usd']:,.0f}) | RMSE val {fold['validation']['rmse_pct']:.2f} % (${fold['validation']['rmse_usd']:,.0f})"
        )
    for side, title in (("train", "entrenamiento"), ("validation", "validación")):
        s = cv["summary"][side]
        print(
            f"{title:13s} MAE ${s['mae_usd']['mean']:,.0f} ± {s['mae_usd']['std']:,.0f} ({s['mae_pct']['mean']:.2f} ± {s['mae_pct']['std']:.2f} %) | "
            f"RMSE ${s['rmse_usd']['mean']:,.0f} ± {s['rmse_usd']['std']:,.0f} ({s['rmse_pct']['mean']:.2f} ± {s['rmse_pct']['std']:.2f} %) | sesgo {s['bias_pct']['mean']:+.2f} %"
        )
    rec = cv["summary"]["validation_recursive"]
    print(f"Validación recursiva 12 meses: MAPE {rec['mape_pct']['mean']:.2f} ± {rec['mape_pct']['std']:.2f} %")
    print("Curva de aprendizaje (MAE %, entrenamiento / validación):")
    for point in results["learning_curve"]["points"]:
        print(f"  {point['train_months']:3d} meses: {point['train']['mae_pct']:.2f} / {point['validation']['mae_pct']:.2f}")
    d = results["diagnosis"]
    print(f"DIAGNÓSTICO: {d['label'].upper()}")
    for reason in d["reasons"]:
        print(f"  - {reason}")
    print("Experimento de regularización (validación cruzada, MAE % entrenamiento -> validación ± std):")
    for row in results["regularization_experiment"]:
        print(f"  {row['variant']:42s} {row['train_mae_pct']:.2f} -> {row['validation_mae_pct_mean']:.2f} ± {row['validation_mae_pct_std']:.2f} (brecha {row['gap_pct_points']:.2f})")
    bg = results["bias_vs_growth"]
    print(f"Sesgo vs crecimiento anual (correlación {bg['correlation_growth_vs_bias']:+.2f}, {bg['folds']} folds):")
    for row in bg["rows"]:
        print(f"  {row['year']}: crecimiento {row['annual_growth_pct']:.1f} % | sesgo {row['bias_pct']:+.2f} % | MAE {row['mae_pct']:.2f} %")
    g = results["growth_feature_experiment"]
    print(f"Feature de crecimiento interanual: MAE validación {g['validation_mae_pct_mean']['baseline']:.2f} % -> {g['validation_mae_pct_mean']['with_growth']:.2f} % (folds 2-5: {g['validation_mae_pct_mean_folds_2_to_5']['baseline']:.2f} -> {g['validation_mae_pct_mean_folds_2_to_5']['with_growth']:.2f}) | mejora: {g['improves']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH, help="CSV de ventas (por defecto data/raw/brasaland_sales.csv)")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Carpeta de salida (por defecto data/eval)")
    args = parser.parse_args()
    print_summary(run(args.data, args.out_dir))


if __name__ == "__main__":
    main()
