"""Entrenamiento, predicción y validación temporal (walk-forward) del modelo de ventas.

Dos formas de predecir, siempre con un modelo entrenado SOLO con meses de entrenamiento:

* **Un mes por delante**: para cada mes de prueba se usan las ventas reales de los meses anteriores.
* **Recursivo** (la principal): se parte del último mes de entrenamiento y cada predicción se reutiliza como
  historia para el mes siguiente. Es lo que ocurriría de verdad al pronosticar los próximos meses, sin conocer
  el futuro, y por eso es la cifra con la que se reporta el error.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from .features import FEATURE_NAMES, build_training_frame, next_month_features, trailing_level
from .metrics import mape, rmse

RANDOM_STATE = 42  # semilla única: el experimento es reproducible bit a bit
MODEL_NAMES = ("random_forest", "xgboost")


def build_model(name: str, random_state: int = RANDOM_STATE) -> Pipeline:
    """Pipeline = escalado + regresor. El escalador se ajusta únicamente con las filas de entrenamiento.

    Los árboles no necesitan escalado para funcionar, pero se incluye para que las features (razones, desviaciones,
    senos/cosenos) se comparen en la misma magnitud y el pipeline siga siendo válido si se cambia a un modelo lineal.
    """
    if name == "random_forest":
        regressor = RandomForestRegressor(
            n_estimators=500, min_samples_leaf=3, max_features=0.7, random_state=random_state, n_jobs=1
        )
    elif name == "xgboost":
        regressor = XGBRegressor(
            n_estimators=300, learning_rate=0.05, max_depth=3, subsample=0.8, colsample_bytree=0.8,
            random_state=random_state, n_jobs=1, objective="reg:squarederror",
        )
    else:
        raise ValueError(f"Modelo desconocido: {name}. Usa uno de {MODEL_NAMES}")
    return Pipeline([("scaler", StandardScaler()), ("regressor", regressor)])


def fit_model(name: str, train_series: pd.Series) -> Pipeline:
    """Entrena con las features construidas únicamente a partir de `train_series`."""
    features, ratio, _ = build_training_frame(train_series)
    model = build_model(name)
    model.fit(features, ratio)
    return model


def predict_next(model: Pipeline, history: pd.Series) -> float:
    """Ventas previstas (USD) del mes siguiente al último de `history`."""
    row = pd.DataFrame([next_month_features(history)], columns=FEATURE_NAMES)
    return float(model.predict(row)[0]) * trailing_level(history)


def one_step_forecast(model: Pipeline, series: pd.Series, targets: pd.DatetimeIndex) -> pd.Series:
    """Para cada mes de `targets`, predice usando las ventas REALES anteriores a ese mes."""
    values = [predict_next(model, series.loc[series.index < month]) for month in targets]
    return pd.Series(values, index=targets, name="one_step")


def recursive_forecast(model: Pipeline, history: pd.Series, horizon: int) -> pd.Series:
    """Pronostica `horizon` meses seguidos reutilizando cada predicción como historia del siguiente."""
    extended = history.copy()
    months, values = [], []
    for _ in range(horizon):
        month = extended.index[-1] + pd.offsets.MonthBegin(1)
        value = predict_next(model, extended)
        extended = pd.concat([extended, pd.Series([value], index=pd.DatetimeIndex([month], freq="MS"))])
        months.append(month)
        values.append(value)
    return pd.Series(values, index=pd.DatetimeIndex(months, freq="MS"), name="recursive")


@dataclass
class CrossValidation:
    """Resultado de la validación walk-forward de un algoritmo (solo con datos de entrenamiento)."""

    name: str
    folds: list[dict]
    rel_errors: np.ndarray  # (real - previsto) / previsto, de las predicciones recursivas de todos los folds

    @property
    def mean_rmse(self) -> float:
        return float(np.mean([fold["rmse_usd"] for fold in self.folds]))

    @property
    def mean_mape(self) -> float:
        return float(np.mean([fold["mape_pct"] for fold in self.folds]))


def walk_forward_cv(name: str, train_series: pd.Series, n_folds: int = 3, horizon: int = 12) -> CrossValidation:
    """Validación temporal: para cada uno de los últimos `n_folds` años de ENTRENAMIENTO, entrena con todo lo anterior
    y pronostica ese año de forma recursiva. Nunca toca el conjunto de prueba, así que sirve para elegir algoritmo
    sin "mirar" los 2 años reservados.
    """
    folds, errors = [], []
    for fold in range(n_folds, 0, -1):
        start = len(train_series) - fold * horizon
        past, future = train_series.iloc[:start], train_series.iloc[start : start + horizon]
        model = fit_model(name, past)
        forecast = recursive_forecast(model, past, horizon)
        errors.extend(((future - forecast) / forecast).tolist())
        folds.append(
            {
                "validation_year": int(future.index[0].year),
                "rmse_usd": rmse(future, forecast),
                "mape_pct": mape(future, forecast),
            }
        )
    return CrossValidation(name=name, folds=folds, rel_errors=np.asarray(errors))


def prediction_band(forecast: pd.Series, rel_errors: np.ndarray, coverage: float = 0.80) -> tuple[pd.Series, pd.Series]:
    """Rango de variabilidad: los errores relativos reales de la validación walk-forward fijan el margen alrededor
    de la predicción (80 % por defecto). Es un rango empírico, no una fórmula teórica."""
    tail = (1 - coverage) / 2
    low_q, high_q = np.quantile(rel_errors, [tail, 1 - tail])
    low_q, high_q = min(low_q, 0.0), max(high_q, 0.0)
    return forecast * (1 + low_q), forecast * (1 + high_q)
