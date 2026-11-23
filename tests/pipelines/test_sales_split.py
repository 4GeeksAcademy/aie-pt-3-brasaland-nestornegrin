"""Pruebas del modelo de ventas: split 8 años / 2 años y ausencia de fuga de datos (data leakage).

La serie sintética de aquí abajo es SOLO un fixture de test (rápido y controlado). Nunca se usa para entrenar
ni para reportar métricas: el modelo real se entrena con `data/raw/brasaland_sales.csv`, que se comprueba
aparte en `test_real_dataset_split` (se salta si el archivo no está en el repo).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.sales_forecast import metrics
from scripts.sales_forecast.data import (
    DEFAULT_DATA_PATH,
    SalesDataError,
    SplitError,
    load_sales,
    split_train_test,
    validate_sales,
)
from scripts.sales_forecast.features import FEATURE_NAMES, MIN_HISTORY, build_training_frame, next_month_features
from scripts.sales_forecast.model import fit_model, recursive_forecast

TARGET = "revenue_usd"


def make_synthetic_sales(years: int = 10, seed: int = 0) -> pd.DataFrame:
    """Fixture de test: 10 años mensuales con crecimiento anual y estacionalidad (enero baja, diciembre sube)."""
    rng = np.random.default_rng(seed)
    months = pd.date_range("2016-01-01", periods=12 * years, freq="MS")
    trend = 500_000 * 1.05 ** (np.arange(len(months)) / 12)
    seasonal = np.where(months.month == 1, 0.85, np.where(months.month == 12, 1.25, 1.0))
    revenue = trend * seasonal * rng.normal(1.0, 0.03, len(months))
    return pd.DataFrame(
        {
            "month": months.strftime("%Y-%m-%d"),
            "revenue_usd": revenue.round(2),
            "covers_served": (revenue / 12).astype(int),
            "avg_ticket_usd": 12.0,
            "market": "consolidated",
        }
    )


@pytest.fixture(scope="module")
def sales() -> pd.DataFrame:
    return validate_sales(make_synthetic_sales())


# ---------------------------------------------------------------------------------------------------------------
# Split 8 años / 2 años
# ---------------------------------------------------------------------------------------------------------------
def test_split_respects_the_8_year_train_2_year_test_rule(sales):
    train, test = split_train_test(sales)

    assert len(train) == 8 * 12 and len(test) == 2 * 12
    assert (train.index.min().year, train.index.max().year) == (2016, 2023)
    assert (test.index.min().year, test.index.max().year) == (2024, 2025)
    # Meses consecutivos, sin huecos, y la prueba es exactamente el final de la serie.
    assert list(train.index) == list(pd.date_range("2016-01-01", "2023-12-01", freq="MS"))
    assert list(test.index) == list(pd.date_range("2024-01-01", "2025-12-01", freq="MS"))


def test_split_has_no_data_leakage_between_sets(sales):
    train, test = split_train_test(sales)

    assert train.index.intersection(test.index).empty  # ningún mes en ambos conjuntos
    assert train.index.max() < test.index.min()  # la prueba es estrictamente posterior: corte temporal, no aleatorio
    assert train.index.union(test.index).equals(sales.index)  # no se pierde ni se inventa ningún mes


def test_split_is_chronological_even_if_the_rows_arrive_shuffled():
    frame = make_synthetic_sales().sample(frac=1, random_state=1)  # filas desordenadas
    train, test = split_train_test(validate_sales(frame))

    assert train.index.is_monotonic_increasing and test.index.is_monotonic_increasing
    assert train.index.max() < test.index.min()
    assert test.index.min() == pd.Timestamp("2024-01-01")


def test_split_rejects_a_series_that_is_too_short():
    short = validate_sales(make_synthetic_sales(years=9))
    with pytest.raises(SplitError):
        split_train_test(short)


# ---------------------------------------------------------------------------------------------------------------
# Sin fuga de datos en features, escalado y predicción
# ---------------------------------------------------------------------------------------------------------------
def test_features_only_use_past_months(sales):
    series = sales[TARGET]
    cut = 60
    tampered = series.copy()
    tampered.iloc[cut:] = tampered.iloc[cut:] * 7  # cambia drásticamente el "futuro" desde el mes 60

    clean_x, clean_y, _ = build_training_frame(series)
    dirty_x, dirty_y, _ = build_training_frame(tampered)

    months_up_to_cut = clean_x.index <= series.index[cut]
    pd.testing.assert_frame_equal(clean_x[months_up_to_cut], dirty_x[months_up_to_cut])  # features intactas
    months_before_cut = clean_x.index < series.index[cut]
    pd.testing.assert_series_equal(clean_y[months_before_cut], dirty_y[months_before_cut])  # objetivos previos intactos
    assert not np.isclose(clean_y.iloc[cut - MIN_HISTORY], dirty_y.iloc[cut - MIN_HISTORY])  # el cambio sí afecta al mes 60


def test_training_and_prediction_share_the_same_features(sales):
    series = sales[TARGET]
    features, _, _ = build_training_frame(series)
    position = 80
    recomputed = next_month_features(series.iloc[:position])  # misma función, solo con el pasado
    assert list(features.columns) == FEATURE_NAMES
    np.testing.assert_allclose(features.loc[series.index[position]].to_numpy(), list(recomputed.values()))


def test_training_frame_stops_at_the_last_training_month(sales):
    train, test = split_train_test(sales)
    features, _, _ = build_training_frame(train[TARGET])

    assert features.index.max() == train.index.max()
    assert features.index.max() < test.index.min()  # ninguna fila de entrenamiento pertenece a la prueba


def test_scaler_is_fitted_with_training_rows_only(sales):
    train, _ = split_train_test(sales)
    model = fit_model("random_forest", train[TARGET])

    train_features, _, _ = build_training_frame(train[TARGET])
    full_features, _, _ = build_training_frame(sales[TARGET])
    scaler = model.named_steps["scaler"]

    np.testing.assert_allclose(scaler.mean_, train_features.mean().to_numpy())  # media = la del entrenamiento
    assert not np.allclose(scaler.mean_, full_features.mean().to_numpy())  # y no la de todos los datos


def test_forecast_does_not_depend_on_test_values(sales):
    """Dos datasets idénticos en entrenamiento y distintos en la prueba deben dar EXACTAMENTE la misma predicción."""
    train, test = split_train_test(sales)
    altered = sales.copy()
    altered.loc[test.index, TARGET] = altered.loc[test.index, TARGET] * 3
    train_b, _ = split_train_test(altered)

    forecast_a = recursive_forecast(fit_model("random_forest", train[TARGET]), train[TARGET], horizon=24)
    forecast_b = recursive_forecast(fit_model("random_forest", train_b[TARGET]), train_b[TARGET], horizon=24)
    pd.testing.assert_series_equal(forecast_a, forecast_b)


def test_training_is_reproducible_with_the_fixed_seed(sales):
    train, _ = split_train_test(sales)
    first = recursive_forecast(fit_model("random_forest", train[TARGET]), train[TARGET], horizon=12)
    second = recursive_forecast(fit_model("random_forest", train[TARGET]), train[TARGET], horizon=12)
    pd.testing.assert_series_equal(first, second)


# ---------------------------------------------------------------------------------------------------------------
# Validación del dataset y métricas
# ---------------------------------------------------------------------------------------------------------------
def test_validate_sales_rejects_missing_months_and_non_positive_revenue():
    with_gap = make_synthetic_sales().drop(index=50)
    with pytest.raises(SalesDataError, match="Faltan meses"):
        validate_sales(with_gap)

    negative = make_synthetic_sales()
    negative.loc[3, TARGET] = -1
    with pytest.raises(SalesDataError, match="positivo"):
        validate_sales(negative)

    with pytest.raises(SalesDataError, match="columnas"):
        validate_sales(make_synthetic_sales().drop(columns=["covers_served"]))


def test_loader_accepts_comma_and_tab_separated_files(tmp_path):
    frame = make_synthetic_sales()
    frame.to_csv(tmp_path / "comma.csv", index=False)
    frame.to_csv(tmp_path / "tab.csv", index=False, sep="\t")
    pd.testing.assert_frame_equal(load_sales(tmp_path / "comma.csv"), load_sales(tmp_path / "tab.csv"))


def test_metrics_behave_as_documented():
    actual = np.array([100.0, 200.0, 300.0, 400.0])
    assert metrics.mse(actual, actual) == 0
    assert metrics.k2_score(actual, actual) == 1
    assert metrics.normalized_gini(actual, actual) == pytest.approx(1)
    assert metrics.normalized_gini(actual, actual[::-1]) < 0  # ordena al revés: peor que el azar
    assert metrics.mape(actual, actual * 1.1) == pytest.approx(10)  # un 10 % de error
    assert metrics.psi(actual, actual) == pytest.approx(0, abs=1e-9)  # misma distribución: sin cambio
    assert metrics.psi(actual, actual + 1_000, bins=4) > 1  # distribuciones disjuntas: cambio enorme


# ---------------------------------------------------------------------------------------------------------------
# Dataset real del curso
# ---------------------------------------------------------------------------------------------------------------
@pytest.mark.skipif(not DEFAULT_DATA_PATH.exists(), reason="data/raw/brasaland_sales.csv no está en el repositorio")
def test_real_dataset_split():
    data = load_sales()
    train, test = split_train_test(data)

    assert len(data) == 120  # 10 años mensuales consolidados
    assert (data.index.min(), data.index.max()) == (pd.Timestamp("2016-01-01"), pd.Timestamp("2025-12-01"))
    assert (train.index.min(), train.index.max()) == (pd.Timestamp("2016-01-01"), pd.Timestamp("2023-12-01"))
    assert (test.index.min(), test.index.max()) == (pd.Timestamp("2024-01-01"), pd.Timestamp("2025-12-01"))
    assert train.index.intersection(test.index).empty
