"""Pruebas de la validación cruzada temporal: orden cronológico de los folds y ausencia de fuga entre ellos.

La prueba clave del ticket es `test_folds_preserve_chronological_order`: ningún índice de un fold posterior aparece
antes que uno de un fold anterior. Las demás comprueban que los folds no barajan datos, que las features de lag y
rolling no ven el futuro de cada fold y que la curva de aprendizaje y el diagnóstico se comportan como se documenta.

La serie sintética es solo un fixture de test (crecimiento del 5 % anual con estacionalidad); el modelo real se evalúa
con `data/raw/brasaland_sales.csv`, que se comprueba aparte (se salta si el archivo no está).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.sales_forecast.data import DEFAULT_DATA_PATH, TARGET, load_sales, split_train_test, validate_sales
from scripts.sales_forecast.evaluation import (
    N_SPLITS,
    VALIDATION_MONTHS,
    Fold,
    FoldOrderError,
    cross_validate,
    diagnose,
    fold_data,
    learning_curve,
    make_folds,
    summarize,
    verify_folds,
)
from scripts.sales_forecast.features import MIN_HISTORY, build_training_frame


def make_series(years: int = 8, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    months = pd.date_range("2016-01-01", periods=12 * years, freq="MS")
    trend = 500_000 * 1.05 ** (np.arange(len(months)) / 12)
    seasonal = np.where(months.month == 1, 0.85, np.where(months.month == 12, 1.25, 1.0))
    revenue = trend * seasonal * rng.normal(1.0, 0.03, len(months))
    frame = pd.DataFrame(
        {
            "month": months.strftime("%Y-%m-%d"),
            "revenue_usd": revenue.round(2),
            "covers_served": (revenue / 12).astype(int),
            "avg_ticket_usd": 12.0,
            "market": "consolidated",
        }
    )
    return validate_sales(frame)[TARGET]


@pytest.fixture(scope="module")
def series() -> pd.Series:
    return make_series()


@pytest.fixture(scope="module")
def folds(series) -> list[Fold]:
    return make_folds(len(series))


def row_months(series: pd.Series) -> pd.DatetimeIndex:
    """Mes al que corresponde cada fila de features (la fila 0 es el mes 13 de la serie)."""
    return build_training_frame(series)[0].index


# ---------------------------------------------------------------------------------------------------------------
# Orden cronológico (la prueba que pide el ticket)
# ---------------------------------------------------------------------------------------------------------------
def test_folds_preserve_chronological_order(series, folds):
    months = row_months(series)
    assert len(folds) >= 5  # el ticket pide al menos 5 folds

    for previous, current in zip(folds, folds[1:]):
        # Ningún índice de un fold posterior aparece antes que uno de un fold anterior (validación y entrenamiento).
        assert current.val_rows.min() > previous.val_rows.max()
        assert months[current.val_rows].min() > months[previous.val_rows].max()
        assert current.train_rows.max() > previous.train_rows.max()  # el entrenamiento crece hacia adelante

    for fold in folds:
        # Dentro de cada fold: orden creciente y el entrenamiento siempre es anterior a la validación.
        assert np.all(np.diff(fold.train_rows) > 0) and np.all(np.diff(fold.val_rows) > 0)
        assert months[fold.train_rows].max() < months[fold.val_rows].min()
        assert set(fold.train_rows).isdisjoint(fold.val_rows)
        assert len(fold.val_rows) == VALIDATION_MONTHS


def test_the_default_strategy_has_five_folds_and_never_shuffles(series, folds):
    assert len(folds) == N_SPLITS == 5
    verify_folds(folds)  # no debe lanzar nada
    assert all(fold.train_rows[0] == 0 for fold in folds)  # ventana creciente: siempre empieza en el primer mes


@pytest.mark.parametrize(
    "broken",
    ["shuffled_train", "validation_before_train", "overlapping_validation", "train_not_growing"],
)
def test_verify_folds_rejects_shuffled_or_overlapping_folds(folds, broken):
    rng = np.random.default_rng(1)
    modified = list(folds)
    if broken == "shuffled_train":
        modified[2] = Fold(3, rng.permutation(folds[2].train_rows), folds[2].val_rows)
    elif broken == "validation_before_train":
        modified[1] = Fold(2, folds[1].val_rows, folds[1].train_rows)
    elif broken == "overlapping_validation":
        modified[3] = Fold(4, folds[3].train_rows, folds[2].val_rows)
    else:
        modified[4] = Fold(5, folds[3].train_rows, folds[4].val_rows)
    with pytest.raises(FoldOrderError):
        verify_folds(modified)


# ---------------------------------------------------------------------------------------------------------------
# Sin fuga de información entre folds
# ---------------------------------------------------------------------------------------------------------------
def test_fold_features_do_not_see_months_after_the_fold(series, folds):
    for fold in folds:
        tampered = series.copy()
        tampered.iloc[fold.series_end :] = tampered.iloc[fold.series_end :] * 9  # cambia todo lo posterior al fold
        for clean, dirty in zip(fold_data(series, fold), fold_data(tampered, fold)):
            pd.testing.assert_index_equal(clean.index, dirty.index)
            np.testing.assert_array_equal(np.asarray(clean), np.asarray(dirty))  # features y objetivos idénticos


def test_fold_features_match_the_full_series_features_for_the_same_months(series, folds):
    """Recortar la serie al final del fold no cambia las features: cada fila solo usa meses anteriores."""
    full_features, full_ratio, _ = build_training_frame(series)
    for fold in folds:
        x_train, y_train, _, x_val, y_val, _ = fold_data(series, fold)
        pd.testing.assert_frame_equal(x_val, full_features.loc[x_val.index])
        pd.testing.assert_series_equal(y_val, full_ratio.loc[y_val.index])
        assert x_train.index.max() < x_val.index.min()  # ninguna fila de entrenamiento es de la validación


def test_cross_validation_does_not_depend_on_months_after_the_last_fold():
    clean = make_series()
    result = cross_validate(clean, recursive=False)
    last_month_shifted = clean.copy()
    last_month_shifted.iloc[-1] = last_month_shifted.iloc[-1] * 3  # el último mes sí es de la última validación
    changed = cross_validate(last_month_shifted, recursive=False)

    for a, b in zip(result["folds"][:-1], changed["folds"][:-1]):  # los 4 primeros folds no ven ese mes
        assert a["validation"] == b["validation"] and a["train"] == b["train"]
    assert result["folds"][-1]["validation"] != changed["folds"][-1]["validation"]


# ---------------------------------------------------------------------------------------------------------------
# Resumen, curva de aprendizaje y diagnóstico
# ---------------------------------------------------------------------------------------------------------------
def test_summary_reports_mean_and_standard_deviation_across_folds():
    keys = ("mae_usd", "rmse_usd", "mae_pct", "rmse_pct", "mape_pct", "bias_pct")
    results = [{"train": dict.fromkeys(keys, value), "validation": dict.fromkeys(keys, value * 2)} for value in (1.0, 2.0, 3.0, 4.0, 5.0)]
    summary = summarize(results)

    assert summary["train"]["mae_usd"]["mean"] == pytest.approx(3.0)
    assert summary["train"]["mae_usd"]["std"] == pytest.approx(np.std([1, 2, 3, 4, 5], ddof=1))
    assert summary["validation"]["rmse_usd"]["mean"] == pytest.approx(6.0)


def test_learning_curve_grows_the_training_set_and_validates_on_a_later_block(series):
    curve = learning_curve(series)
    sizes = [point["train_months"] for point in curve]
    rows = len(series) - MIN_HISTORY

    assert sizes == sorted(set(sizes)) and len(sizes) >= 5  # el entrenamiento crece de verdad
    assert max(sizes) + VALIDATION_MONTHS <= rows  # la validación es siempre posterior a todo el entrenamiento
    assert all(point["train"]["mae_pct"] >= 0 and point["validation"]["mae_pct"] >= 0 for point in curve)


def _curve(train: list[float], validation: list[float]) -> list[dict]:
    return [
        {"train_months": 12 + 6 * i, "train": {"mae_pct": t}, "validation": {"mae_pct": v}}
        for i, (t, v) in enumerate(zip(train, validation))
    ]


def test_diagnosis_classifies_the_three_learning_curve_patterns():
    noise = 2.0
    overfit = _curve([3.0, 2.0, 1.0, 0.8, 0.6], [5.0, 4.6, 4.4, 4.4, 4.4])  # entrenamiento bajo el ruido, brecha que persiste
    underfit = _curve([6.0, 6.0, 5.8, 5.8, 5.7], [6.5, 6.4, 6.2, 6.2, 6.1])  # ambas curvas altas y juntas
    healthy = _curve([3.0, 2.8, 2.4, 2.2, 2.1], [3.4, 3.1, 2.8, 2.6, 2.5])  # ambas bajas y cercanas

    assert diagnose(overfit, noise)["label"] == "overfitting"
    assert diagnose(underfit, noise)["label"] == "underfitting"
    assert diagnose(healthy, noise)["label"] == "bien ajustado"


@pytest.mark.skipif(not DEFAULT_DATA_PATH.exists(), reason="data/raw/brasaland_sales.csv no está en el repositorio")
def test_real_dataset_folds_are_chronological_and_use_only_training_months():
    train, test = split_train_test(load_sales())
    folds = make_folds(len(train))
    verify_folds(folds)

    months = row_months(train[TARGET])
    assert len(folds) >= 5
    assert months[folds[-1].val_rows].max() == train.index.max()  # el último fold llega al último mes de entrenamiento...
    assert months.max() < test.index.min()  # ...y ningún fold toca los 2 años de prueba

    result = cross_validate(train[TARGET], recursive=False)
    assert result["n_splits"] == len(folds)
    assert {"mean", "std"} <= set(result["summary"]["validation"]["mae_usd"])
