"""Métricas del informe: MSE, PSI, Gini y K2 Score (R²), siempre sobre el conjunto de prueba."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import mean_squared_error, r2_score


def mse(actual, predicted) -> float:
    """Error cuadrático medio, en USD²."""
    return float(mean_squared_error(actual, predicted))


def mae(actual, predicted) -> float:
    """Error absoluto medio (en USD si las ventas están en USD): el error típico, sin dar más peso a los grandes."""
    return float(np.mean(np.abs(np.asarray(actual, dtype=float) - np.asarray(predicted, dtype=float))))


def rmse(actual, predicted) -> float:
    """Raíz del MSE, en USD: es el error típico en dólares."""
    return float(np.sqrt(mse(actual, predicted)))


def mape(actual, predicted) -> float:
    """Error porcentual absoluto medio (%): lo que se le explica a Finanzas ("nos equivocamos un X %")."""
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    return float(np.mean(np.abs((actual - predicted) / actual)) * 100)


def k2_score(actual, predicted) -> float:
    """K2 Score, interpretado como R² (coeficiente de determinación): 1 = perfecto, 0 = igual que predecir la media."""
    return float(r2_score(actual, predicted))


def psi(expected, actual, bins: int = 10, epsilon: float = 1e-4) -> float:
    """Population Stability Index entre dos distribuciones (`expected` = entrenamiento, `actual` = prueba).

    Los cortes salen de los deciles de `expected`. Referencia habitual: < 0.10 estable, 0.10-0.25 cambio moderado,
    > 0.25 cambio significativo (la población ya no se parece a la de entrenamiento).
    """
    expected, actual = np.asarray(expected, dtype=float), np.asarray(actual, dtype=float)
    edges = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    expected_share = np.histogram(expected, bins=edges)[0] / len(expected)
    actual_share = np.histogram(actual, bins=edges)[0] / len(actual)
    expected_share, actual_share = np.clip(expected_share, epsilon, None), np.clip(actual_share, epsilon, None)
    return float(np.sum((actual_share - expected_share) * np.log(actual_share / expected_share)))


def _gini(actual: np.ndarray, ranking: np.ndarray) -> float:
    order = np.lexsort((np.arange(len(actual)), -ranking))  # mayor puntuación primero; empates por posición
    cumulative = np.cumsum(actual[order]) / actual.sum()
    return float(cumulative.sum() / len(actual) - (len(actual) + 1) / (2 * len(actual)))


def normalized_gini(actual, predicted) -> float:
    """Gini normalizado: capacidad del modelo para ORDENAR los meses de mejor a peor.

    1 = ordena igual que la realidad, 0 = no distingue meses buenos de malos (orden aleatorio).
    """
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    return _gini(actual, predicted) / _gini(actual, actual)


def psi_noise_threshold(
    expected, actual, bins: int = 5, permutations: int = 2000, quantile: float = 0.95, seed: int = 42
) -> float:
    """PSI que aparece solo por azar al repartir las mismas observaciones entre dos grupos de este tamaño.

    Con pocos datos (aquí 24 meses de prueba) el PSI sale alto aunque no haya ningún cambio real: los tramos con
    pocos o ningún punto inflan el índice. Los umbrales genéricos (0.10 / 0.25) no sirven con muestras tan pequeñas,
    así que el PSI observado se compara contra este umbral por permutación.
    """
    expected, actual = np.asarray(expected, dtype=float), np.asarray(actual, dtype=float)
    pooled, rng = np.concatenate([expected, actual]), np.random.default_rng(seed)
    values = []
    for _ in range(permutations):
        rng.shuffle(pooled)
        values.append(psi(pooled[: len(expected)], pooled[len(expected) :], bins=bins))
    return float(np.quantile(values, quantile))


def psi_reading(value: float, noise_threshold: float) -> str:
    """Interpretación honesta: solo hay cambio si el PSI supera lo que produciría el azar."""
    return "cambio real (supera el ruido muestral)" if value > noise_threshold else "dentro del ruido muestral (sin cambio)"
