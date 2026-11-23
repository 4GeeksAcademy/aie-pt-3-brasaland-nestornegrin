"""Descomposición de las ventas en tendencia, estacionalidad y residuo (análisis exploratorio).

Se usa STL (Seasonal-Trend decomposition using Loess) sobre el **logaritmo** de las ventas. Es el mismo modelo que
una descomposición multiplicativa:

    ventas_t = tendencia_t × factor_estacional_t × factor_residuo_t

¿Por qué multiplicativa? En Brasaland la estacionalidad crece con el nivel: diciembre sube ≈ 20-27 % sobre la media
del año, no una cantidad fija de dólares. Con logaritmos, cada componente se lee como un porcentaje.

Solo se descompone la serie que se le pasa. El script la llama únicamente con los meses de ENTRENAMIENTO, así que el
análisis exploratorio nunca ve los 2 años de prueba.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL

PERIOD = 12  # estacionalidad anual en datos mensuales
MONTH_NAMES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


@dataclass(frozen=True)
class Decomposition:
    """Componentes (en dólares y en factores) más las cifras resumen que se citan en el README."""

    observed: pd.Series  # ventas reales (USD)
    trend: pd.Series  # nivel subyacente (USD): sin estacionalidad ni ruido
    seasonal: pd.Series  # factor multiplicativo (1,00 = mes normal; 1,25 = un 25 % por encima)
    residual: pd.Series  # factor multiplicativo del ruido (1,00 = sin ruido)
    summary: dict

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {"observed_usd": self.observed, "trend_usd": self.trend, "seasonal_factor": self.seasonal, "residual_factor": self.residual}
        )


def decompose(series: pd.Series) -> Decomposition:
    """Descompone `series` (ventas mensuales, estrictamente positivas) con STL robusto sobre logaritmos."""
    if len(series) < 2 * PERIOD:
        raise ValueError(f"Se necesitan al menos {2 * PERIOD} meses para descomponer y hay {len(series)}")
    if (series <= 0).any():
        raise ValueError("La descomposición multiplicativa exige ventas positivas")

    logged = np.log(series.astype(float))
    fit = STL(logged, period=PERIOD, robust=True).fit()  # robust: un mes atípico no deforma la tendencia
    trend, seasonal, residual = np.exp(fit.trend), np.exp(fit.seasonal), np.exp(fit.resid)

    var_resid = float(np.var(fit.resid))
    # Fuerza de cada componente (Hyndman): 0 = no explica nada, 1 = explica toda la variación.
    seasonal_strength = max(0.0, 1 - var_resid / float(np.var(fit.seasonal + fit.resid)))
    trend_strength = max(0.0, 1 - var_resid / float(np.var(fit.trend + fit.resid)))

    months = len(series)
    annual_growth = float((trend.iloc[-1] / trend.iloc[0]) ** (12 / (months - 1)) - 1)
    by_month = seasonal.groupby(seasonal.index.month).mean()  # factor medio de cada mes del año
    residual_pct = (residual - 1) * 100

    summary = {
        "method": "STL robusto sobre logaritmos (descomposición multiplicativa), periodo 12",
        "months_used": int(months),
        "range": [series.index.min().strftime("%Y-%m"), series.index.max().strftime("%Y-%m")],
        "trend": {
            "annual_growth_pct": annual_growth * 100,
            "first_usd": float(trend.iloc[0]),
            "last_usd": float(trend.iloc[-1]),
            "strength": trend_strength,
        },
        "seasonality": {
            "strength": seasonal_strength,
            "factor_by_month": {name: float(by_month.loc[number]) for number, name in enumerate(MONTH_NAMES, start=1)},
            "lowest_month": MONTH_NAMES[int(by_month.idxmin()) - 1],
            "highest_month": MONTH_NAMES[int(by_month.idxmax()) - 1],
        },
        "residual": {
            "std_pct": float(residual_pct.std(ddof=0)),
            "mean_abs_pct": float(residual_pct.abs().mean()),
            "max_abs_pct": float(residual_pct.abs().max()),
        },
    }
    return Decomposition(series.astype(float), trend, seasonal, residual, summary)
