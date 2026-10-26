"""Pruebas de la descomposición en tendencia, estacionalidad y residuo (análisis exploratorio).

Igual que en `test_sales_split.py`, la serie sintética es solo un fixture de test, con una estructura conocida
(crecimiento del 5 % anual, enero a 0,85 y diciembre a 1,25) para comprobar que la descomposición la recupera.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.sales_forecast.data import DEFAULT_DATA_PATH, TARGET, load_sales, split_train_test, validate_sales
from scripts.sales_forecast.decomposition import decompose


def make_series(years: int = 10, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    months = pd.date_range("2016-01-01", periods=12 * years, freq="MS")
    trend = 500_000 * 1.05 ** (np.arange(len(months)) / 12)
    seasonal = np.where(months.month == 1, 0.85, np.where(months.month == 12, 1.25, 1.0))
    revenue = trend * seasonal * rng.normal(1.0, 0.03, len(months))
    return validate_sales(
        pd.DataFrame(
            {
                "month": months.strftime("%Y-%m-%d"),
                "revenue_usd": revenue.round(2),
                "covers_served": (revenue / 12).astype(int),
                "avg_ticket_usd": 12.0,
                "market": "consolidated",
            }
        )
    )


def test_components_rebuild_the_original_series():
    series = make_series()[TARGET]
    result = decompose(series)

    rebuilt = result.trend * result.seasonal * result.residual  # ventas = tendencia × estacionalidad × residuo
    pd.testing.assert_series_equal(rebuilt, series, check_names=False, check_freq=False, rtol=1e-9)


def test_decomposition_recovers_the_known_structure():
    summary = decompose(make_series()[TARGET]).summary

    assert 4.0 < summary["trend"]["annual_growth_pct"] < 6.0  # el fixture crece un 5 % anual
    assert summary["seasonality"]["lowest_month"] == "ene" and summary["seasonality"]["highest_month"] == "dic"
    assert summary["seasonality"]["factor_by_month"]["ene"] < 0.9
    assert summary["seasonality"]["factor_by_month"]["dic"] > 1.15
    assert summary["seasonality"]["strength"] > 0.8
    assert summary["residual"]["std_pct"] < 5  # el ruido del fixture es del 3 %


def test_decomposition_only_uses_training_months():
    sales = make_series()
    train, test = split_train_test(sales)
    result = decompose(train[TARGET])

    assert result.trend.index.equals(train.index)
    assert result.trend.index.max() < test.index.min()  # ningún mes de prueba entra en el análisis

    altered = sales.copy()
    altered.loc[test.index, TARGET] = altered.loc[test.index, TARGET] * 5  # cambiar la prueba no debe alterar nada
    train_b, _ = split_train_test(altered)
    pd.testing.assert_frame_equal(result.to_frame(), decompose(train_b[TARGET]).to_frame())


def test_decompose_rejects_short_or_non_positive_series():
    series = make_series()[TARGET]
    with pytest.raises(ValueError, match="al menos"):
        decompose(series.iloc[:20])
    broken = series.copy()
    broken.iloc[5] = 0.0
    with pytest.raises(ValueError, match="positivas"):
        decompose(broken)


@pytest.mark.skipif(not DEFAULT_DATA_PATH.exists(), reason="data/raw/brasaland_sales.csv no está en el repositorio")
def test_real_dataset_decomposition_matches_the_documented_pattern():
    train, _ = split_train_test(load_sales())
    summary = decompose(train[TARGET]).summary

    assert summary["months_used"] == 96
    assert 3.0 < summary["trend"]["annual_growth_pct"] < 8.0  # el briefing habla de un crecimiento del 3-7 %
    assert summary["seasonality"]["lowest_month"] == "ene" and summary["seasonality"]["highest_month"] == "dic"
    assert summary["seasonality"]["strength"] > 0.8
