"""Evaluación técnica del modelo de ventas: validación cruzada temporal, curva de aprendizaje y diagnóstico.

Todo se hace SOLO con los 96 meses de entrenamiento: el conjunto de prueba (2024-2025) no interviene.

Piezas:

* **Folds** con `TimeSeriesSplit` (5 folds, cada uno valida un año completo, el entrenamiento crece y siempre
  empieza en el primer mes). `verify_folds` comprueba de forma explícita que ningún fold mezcla ni baraja datos.
* **Features sin fuga entre folds**: las features de cada fold se construyen con la serie recortada al final de su
  ventana de validación (`fold_data`). Los meses posteriores ni existen para ese fold, y cada feature de un mes usa
  solo meses anteriores.
* **Curva de aprendizaje**: error de entrenamiento y de validación al crecer el entrenamiento (de 12 a 72 filas),
  con una validación fija (el último año de entrenamiento).
* **Diagnóstico** con una regla fijada ANTES de mirar los resultados, comparando contra el ruido irreducible
  estimado con la descomposición de la serie (el residuo).

Tanto el error de entrenamiento como el de validación son "un mes por delante" (se usan las ventas reales de los
meses anteriores), para que sean comparables entre sí. Además se reporta el error recursivo de 12 meses de cada fold.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .decomposition import decompose
from .features import MIN_HISTORY, build_training_frame
from .metrics import mae, mape, rmse
from .model import RANDOM_STATE, build_model, recursive_forecast

N_SPLITS = 5  # el ticket pide al menos 5
VALIDATION_MONTHS = 12  # cada fold valida un año completo
MIN_CURVE_SIZE = 12  # tamaño mínimo de entrenamiento de la curva (filas)
CURVE_STEP = 6

# Regla de diagnóstico, fijada antes de calcular nada. "Ruido" = error mínimo que un modelo no puede bajar porque
# es azar de la serie (residuo de la descomposición, en % medio absoluto).
FIT_BELOW_NOISE = 0.75  # entrenamiento por debajo de 0,75 x ruido: el modelo está memorizando ruido
GAP_MIN = 0.5  # y la brecha validación - entrenamiento supera 0,5 x ruido (puntos porcentuales)
GAP_CLOSING_RATIO = 0.8  # la brecha "se cierra" si al final es < 0,8 x la brecha a mitad de la curva
UNDERFIT_ABOVE_NOISE = 1.5  # entrenamiento por encima de 1,5 x ruido: ni siquiera ajusta los datos que ve
UNDERFIT_CURVE_RATIO = 1.3  # y validación / entrenamiento < 1,3: ambas curvas altas y juntas

ERROR_KEYS = ("mae_usd", "rmse_usd", "mae_pct", "rmse_pct", "mape_pct", "bias_pct")


class FoldOrderError(ValueError):
    """Los folds mezclan, barajan o no respetan el orden cronológico."""


@dataclass(frozen=True)
class Fold:
    """Un fold, expresado en posiciones de filas de la matriz de features (la fila 0 es el mes 13 de la serie)."""

    number: int
    train_rows: np.ndarray
    val_rows: np.ndarray

    @property
    def series_end(self) -> int:
        """Meses de la serie visibles para este fold: hasta el final de su ventana de validación y ni uno más."""
        return MIN_HISTORY + int(self.val_rows[-1]) + 1


def make_folds(n_months: int, n_splits: int = N_SPLITS, validation_months: int = VALIDATION_MONTHS) -> list[Fold]:
    """`TimeSeriesSplit` sobre las filas útiles de la serie (los primeros 12 meses solo dan historia)."""
    rows = n_months - MIN_HISTORY
    splitter = TimeSeriesSplit(n_splits=n_splits, test_size=validation_months)
    return [Fold(number, train, val) for number, (train, val) in enumerate(splitter.split(np.arange(rows)), start=1)]


def verify_folds(folds: list[Fold]) -> None:
    """Comprueba de forma explícita que ningún fold mezcla ni baraja los datos. Lanza `FoldOrderError` si falla."""
    if not folds:
        raise FoldOrderError("No hay folds")
    previous_val_end, previous_train_size = -1, 0
    for fold in folds:
        train, val = fold.train_rows, fold.val_rows
        if not (np.all(np.diff(train) == 1) and np.all(np.diff(val) == 1)):
            raise FoldOrderError(f"Fold {fold.number}: los índices no son consecutivos y crecientes (¿datos barajados?)")
        if train[0] != 0:
            raise FoldOrderError(f"Fold {fold.number}: el entrenamiento debe empezar en el primer mes")
        if np.intersect1d(train, val).size or train[-1] >= val[0]:
            raise FoldOrderError(f"Fold {fold.number}: el entrenamiento no es estrictamente anterior a la validación")
        if val[0] <= previous_val_end:
            raise FoldOrderError(f"Fold {fold.number}: su validación no es posterior a la del fold anterior")
        if len(train) <= previous_train_size:
            raise FoldOrderError(f"Fold {fold.number}: el entrenamiento no crece respecto al fold anterior")
        previous_val_end, previous_train_size = int(val[-1]), len(train)


def fold_data(series: pd.Series, fold: Fold):
    """Features y objetivos del fold, construidos con la serie recortada al final de su validación.

    Devuelve (X_train, y_train, level_train, X_val, y_val, level_val). `level` es la media de los 12 meses previos.
    """
    visible = series.iloc[: fold.series_end]
    features, ratio, level = build_training_frame(visible)
    if features.index[-1] != visible.index[-1]:
        raise FoldOrderError(f"Fold {fold.number}: las features no terminan en el último mes visible")
    tr, va = fold.train_rows, fold.val_rows
    return features.iloc[tr], ratio.iloc[tr], level.iloc[tr], features.iloc[va], ratio.iloc[va], level.iloc[va]


def error_block(model: Pipeline, features: pd.DataFrame, ratio: pd.Series, level: pd.Series) -> dict:
    """Errores un mes por delante, en USD y en % del nivel de ventas. `bias_pct` > 0 = sobreestima."""
    predicted_ratio = model.predict(features)
    actual_ratio = ratio.to_numpy()
    scale = level.to_numpy()
    actual, predicted = actual_ratio * scale, predicted_ratio * scale
    return {
        "mae_usd": mae(actual, predicted),
        "rmse_usd": rmse(actual, predicted),
        "mae_pct": float(np.mean(np.abs(predicted_ratio - actual_ratio)) * 100),
        "rmse_pct": float(np.sqrt(np.mean((predicted_ratio - actual_ratio) ** 2)) * 100),
        "mape_pct": mape(actual, predicted),
        "bias_pct": float(np.mean((predicted - actual) / actual) * 100),
    }


def baseline_builder() -> Pipeline:
    """El modelo ya elegido y entrenado en el PR anterior (Random Forest), sin cambios."""
    return build_model("random_forest")


def forest_builder(min_samples_leaf: int, max_features: float) -> Callable[[], Pipeline]:
    """Variante del Random Forest con más o menos regularización (para el experimento de la acción correctiva)."""

    def build() -> Pipeline:
        regressor = RandomForestRegressor(
            n_estimators=500, min_samples_leaf=min_samples_leaf, max_features=max_features,
            random_state=RANDOM_STATE, n_jobs=1,
        )
        return Pipeline([("scaler", StandardScaler()), ("regressor", regressor)])

    return build


def evaluate_fold(series: pd.Series, fold: Fold, builder: Callable[[], Pipeline], recursive: bool = True) -> dict:
    x_train, y_train, level_train, x_val, y_val, level_val = fold_data(series, fold)
    model = builder()
    model.fit(x_train, y_train)  # el escalador se ajusta aquí, solo con las filas de entrenamiento del fold
    result = {
        "fold": fold.number,
        "train_rows": int(len(x_train)),
        "validation_rows": int(len(x_val)),
        "train_window": [x_train.index[0].strftime("%Y-%m"), x_train.index[-1].strftime("%Y-%m")],
        "validation_window": [x_val.index[0].strftime("%Y-%m"), x_val.index[-1].strftime("%Y-%m")],
        "train": error_block(model, x_train, y_train, level_train),
        "validation": error_block(model, x_val, y_val, level_val),
    }
    if recursive:  # pronóstico de 12 meses seguidos, sin ver el año de validación
        start = MIN_HISTORY + int(fold.val_rows[0])
        forecast = recursive_forecast(model, series.iloc[:start], len(fold.val_rows))
        actual = series.iloc[start : start + len(fold.val_rows)]
        result["validation_recursive"] = {"mape_pct": mape(actual, forecast), "rmse_usd": rmse(actual, forecast)}
    return result


def summarize(results: list[dict]) -> dict:
    """Media y desviación estándar (muestral, ddof=1) a través de los folds, para entrenamiento y validación."""

    def stats(values: list[float]) -> dict:
        array = np.asarray(values, dtype=float)
        return {"mean": float(array.mean()), "std": float(array.std(ddof=1))}

    summary = {side: {key: stats([r[side][key] for r in results]) for key in ERROR_KEYS} for side in ("train", "validation")}
    if all("validation_recursive" in r for r in results):
        summary["validation_recursive"] = {
            key: stats([r["validation_recursive"][key] for r in results]) for key in ("mape_pct", "rmse_usd")
        }
    return summary


def cross_validate(series: pd.Series, builder: Callable[[], Pipeline] = baseline_builder, recursive: bool = True) -> dict:
    folds = make_folds(len(series))
    verify_folds(folds)
    results = [evaluate_fold(series, fold, builder, recursive) for fold in folds]
    return {"n_splits": len(folds), "folds": results, "summary": summarize(results)}


def learning_curve(series: pd.Series, builder: Callable[[], Pipeline] = baseline_builder) -> list[dict]:
    """Error de entrenamiento y de validación según crece el entrenamiento.

    La validación es fija (el último año de entrenamiento) y el entrenamiento son las primeras `n` filas, siempre
    anteriores a ella; así la única diferencia entre puntos es el tamaño. Cada fila usa solo meses anteriores.
    """
    features, ratio, level = build_training_frame(series)
    split = len(features) - VALIDATION_MONTHS
    x_val, y_val, level_val = features.iloc[split:], ratio.iloc[split:], level.iloc[split:]
    points = []
    for size in range(MIN_CURVE_SIZE, split + 1, CURVE_STEP):
        x_train, y_train, level_train = features.iloc[:size], ratio.iloc[:size], level.iloc[:size]
        model = builder()
        model.fit(x_train, y_train)
        points.append(
            {
                "train_months": size,
                "train": error_block(model, x_train, y_train, level_train),
                "validation": error_block(model, x_val, y_val, level_val),
            }
        )
    return points


def noise_floor_pct(series: pd.Series) -> float:
    """Ruido irreducible estimado: desvío medio absoluto del residuo de la descomposición (en %)."""
    return float(decompose(series).summary["residual"]["mean_abs_pct"])


def diagnose(curve: list[dict], noise_pct: float) -> dict:
    """Clasifica el modelo con la regla fijada arriba, usando el MAE (en % del nivel) de la curva de aprendizaje."""
    last, middle = curve[-1], curve[len(curve) // 2]
    train_error, val_error = last["train"]["mae_pct"], last["validation"]["mae_pct"]
    gap, gap_middle = val_error - train_error, middle["validation"]["mae_pct"] - middle["train"]["mae_pct"]
    closing = gap < GAP_CLOSING_RATIO * gap_middle

    reasons = [
        f"Con todo el entrenamiento ({last['train_months']} meses): error de entrenamiento {train_error:.2f} % y de "
        f"validación {val_error:.2f} % (ruido irreducible estimado: {noise_pct:.2f} %).",
        f"Brecha validación - entrenamiento: {gap:.2f} puntos al final y {gap_middle:.2f} a mitad de la curva "
        f"({middle['train_months']} meses): {'se estrecha' if closing else 'no se estrecha'}.",
    ]
    if train_error < FIT_BELOW_NOISE * noise_pct and gap > GAP_MIN * noise_pct and not closing:
        label = "overfitting"
        reasons.append(
            f"El entrenamiento queda por debajo del ruido ({train_error:.2f} % < {FIT_BELOW_NOISE} x {noise_pct:.2f} %): "
            "ningún modelo honesto puede acertar tanto, así que memoriza ruido. Y la brecha persiste al crecer los datos."
        )
    elif train_error > UNDERFIT_ABOVE_NOISE * noise_pct and val_error / train_error < UNDERFIT_CURVE_RATIO:
        label = "underfitting"
        reasons.append("Ambas curvas son altas y están juntas: el modelo no captura el patrón ni en los datos que ve.")
    else:
        label = "bien ajustado"
        reasons.append("No se cumple ninguna de las dos condiciones de fallo definidas de antemano.")
    return {
        "label": label,
        "reasons": reasons,
        "noise_floor_pct": noise_pct,
        "train_mae_pct": train_error,
        "validation_mae_pct": val_error,
        "gap_pct_points": gap,
        "gap_at_middle_pct_points": gap_middle,
        "gap_closing": bool(closing),
        "rule": {
            "overfitting": f"MAE entrenamiento < {FIT_BELOW_NOISE} x ruido, brecha > {GAP_MIN} x ruido y brecha que no se cierra (< {GAP_CLOSING_RATIO} x la de mitad de curva)",
            "underfitting": f"MAE entrenamiento > {UNDERFIT_ABOVE_NOISE} x ruido y validación / entrenamiento < {UNDERFIT_CURVE_RATIO}",
            "bien ajustado": "ninguna de las dos anteriores",
        },
    }


REGULARIZATION_VARIANTS = (
    ("actual (hoja mín. 3, 70 % de variables)", 3, 0.7),
    ("hoja mín. 6, 70 % de variables", 6, 0.7),
    ("hoja mín. 10, 70 % de variables", 10, 0.7),
    ("hoja mín. 6, 40 % de variables", 6, 0.4),
    ("hoja mín. 10, 40 % de variables", 10, 0.4),
)


def regularization_experiment(series: pd.Series) -> list[dict]:
    """Evidencia para la acción correctiva: la misma validación cruzada con más regularización (solo entrenamiento)."""
    rows = []
    for label, leaf, features in REGULARIZATION_VARIANTS:
        summary = cross_validate(series, forest_builder(leaf, features), recursive=False)["summary"]
        train, val = summary["train"]["mae_pct"], summary["validation"]["mae_pct"]
        rows.append(
            {
                "variant": label,
                "min_samples_leaf": leaf,
                "max_features": features,
                "train_mae_pct": train["mean"],
                "validation_mae_pct_mean": val["mean"],
                "validation_mae_pct_std": val["std"],
                "validation_rmse_pct_mean": summary["validation"]["rmse_pct"]["mean"],
                "gap_pct_points": val["mean"] - train["mean"],
            }
        )
    return rows


def bias_vs_growth(series: pd.Series, cv: dict) -> dict:
    """Relaciona el sesgo de cada fold con el crecimiento del año que valida (causa del error que sobra sobre el ruido).

    `bias_pct` > 0 = el modelo sobreestima ese año. Con solo 5 folds la correlación es orientativa.
    """
    annual = series.groupby(series.index.year).mean()
    growth = (annual.pct_change() * 100).dropna()
    rows = []
    for fold in cv["folds"]:
        year = int(fold["validation_window"][0][:4])
        rows.append({"year": year, "annual_growth_pct": float(growth.loc[year]), "bias_pct": fold["validation"]["bias_pct"], "mae_pct": fold["validation"]["mae_pct"]})
    correlation = float(np.corrcoef([r["annual_growth_pct"] for r in rows], [r["bias_pct"] for r in rows])[0, 1])
    return {"rows": rows, "correlation_growth_vs_bias": correlation, "folds": len(rows)}


def _yoy_growth(series: pd.Series, months: pd.DatetimeIndex) -> pd.Series:
    """Crecimiento interanual a la fecha de cada mes: media de los 12 meses previos / media de los 12 anteriores - 1."""
    values = []
    for month in months:
        position = series.index.get_loc(month)
        values.append(series.iloc[position - 12 : position].mean() / series.iloc[position - 24 : position - 12].mean() - 1 if position >= 24 else np.nan)
    return pd.Series(values, index=months)


def growth_feature_experiment(series: pd.Series) -> dict:
    """Prueba (solo entrenamiento) si darle al modelo el crecimiento del último año reduce el error de validación.

    La feature necesita 24 meses de historia, así que el entrenamiento de cada fold pierde 12 filas: es una
    desventaja para la variante y se reporta también la media de los folds 2-5, donde el efecto pesa menos.
    """
    def run(with_growth: bool) -> list[dict]:
        rows = []
        for fold in make_folds(len(series)):
            visible = series.iloc[: fold.series_end]
            features, ratio, _ = build_training_frame(visible)
            if with_growth:
                features = features.assign(yoy_growth=_yoy_growth(visible, features.index))
            x_train, y_train = features.iloc[fold.train_rows], ratio.iloc[fold.train_rows]
            complete = x_train.notna().all(axis=1)
            model = baseline_builder()
            model.fit(x_train[complete], y_train[complete])
            predicted, actual = model.predict(features.iloc[fold.val_rows]), ratio.iloc[fold.val_rows].to_numpy()
            rows.append({"fold": fold.number, "train_rows": int(complete.sum()), "mae_pct": float(np.mean(np.abs(predicted - actual)) * 100)})
        return rows

    base, variant = run(False), run(True)
    mean = lambda rows, skip=0: float(np.mean([r["mae_pct"] for r in rows[skip:]]))  # noqa: E731
    return {
        "feature": "yoy_growth: media de los 12 meses previos / media de los 12 anteriores - 1",
        "baseline_folds": base,
        "with_growth_folds": variant,
        "validation_mae_pct_mean": {"baseline": mean(base), "with_growth": mean(variant)},
        "validation_mae_pct_mean_folds_2_to_5": {"baseline": mean(base, 1), "with_growth": mean(variant, 1)},
        "improves": bool(mean(variant) < mean(base)),
    }
