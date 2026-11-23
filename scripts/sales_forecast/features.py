"""Features causales para predecir `revenue_usd`.

Idea central: las ventas crecen cada año (3-7 %), así que un árbol que aprendiera niveles absolutos nunca
podría predecir un mes por encima del máximo visto en entrenamiento. Por eso el modelo no predice dólares,
predice una **razón** respecto al nivel reciente:

    nivel_t   = media de los 12 meses anteriores a t          (solo información pasada)
    razón_t   = ventas_t / nivel_t                            (variable objetivo, sin escala)
    ventas_t  = razón_t * nivel_t                             (se vuelve a USD al predecir)

Todas las features de un mes `t` se calculan con meses < t. Esa misma función (`next_month_features`) se usa
para entrenar y para predecir, así que no puede haber desajuste ni fuga de información entre ambos.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_HISTORY = 12  # meses de pasado necesarios para calcular el nivel y el lag estacional

FEATURE_NAMES = [
    "lag1_ratio",  # ventas del mes anterior / nivel
    "lag2_ratio",
    "lag3_ratio",
    "lag12_ratio",  # mismo mes del año pasado / nivel: captura la estacionalidad (enero baja, diciembre sube)
    "roll3_ratio",  # media móvil de 3 meses / nivel
    "roll6_ratio",  # media móvil de 6 meses / nivel
    "roll6_cv",  # volatilidad reciente (desviación típica 6 meses / nivel)
    "trend_6m",  # crecimiento: últimos 6 meses frente a los 6 anteriores
    "month_sin",  # calendario (circular, para que diciembre y enero queden juntos)
    "month_cos",
    "is_january",
    "is_december",
]


def trailing_level(history: pd.Series) -> float:
    """Nivel reciente: media de los últimos 12 meses de `history` (todos anteriores al mes a predecir)."""
    return float(history.iloc[-12:].mean())


def next_month_features(history: pd.Series) -> dict[str, float]:
    """Features del mes siguiente al último de `history`, usando únicamente `history`."""
    if len(history) < MIN_HISTORY:
        raise ValueError(f"Se necesitan al menos {MIN_HISTORY} meses de historia y hay {len(history)}")
    values = history.to_numpy(dtype=float)
    level = float(values[-12:].mean())
    month = (history.index[-1] + pd.offsets.MonthBegin(1)).month
    angle = 2 * np.pi * month / 12
    return {
        "lag1_ratio": values[-1] / level,
        "lag2_ratio": values[-2] / level,
        "lag3_ratio": values[-3] / level,
        "lag12_ratio": values[-12] / level,
        "roll3_ratio": values[-3:].mean() / level,
        "roll6_ratio": values[-6:].mean() / level,
        "roll6_cv": values[-6:].std() / level,
        "trend_6m": values[-6:].mean() / values[-12:-6].mean() - 1,
        "month_sin": float(np.sin(angle)),
        "month_cos": float(np.cos(angle)),
        "is_january": float(month == 1),
        "is_december": float(month == 12),
    }


def build_training_frame(series: pd.Series) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Matriz de entrenamiento a partir de `series`.

    Devuelve (X, y_ratio, level), todos indexados por el mes objetivo. Para el mes i solo se usa `series[:i]`.
    """
    rows, targets, levels, index = [], [], [], []
    for position in range(MIN_HISTORY, len(series)):
        history = series.iloc[:position]
        level = trailing_level(history)
        rows.append(next_month_features(history))
        targets.append(series.iloc[position] / level)
        levels.append(level)
        index.append(series.index[position])
    features = pd.DataFrame(rows, index=pd.DatetimeIndex(index), columns=FEATURE_NAMES)
    return features, pd.Series(targets, index=features.index, name="ratio"), pd.Series(levels, index=features.index, name="level")
