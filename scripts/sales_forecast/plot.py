"""Visualización: predicción + rango de variabilidad frente a las ventas reales de los 2 años de prueba."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sin pantalla: funciona igual en Codespaces, CI o servidor
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402


def plot_forecast(
    train: pd.Series,
    test: pd.Series,
    forecast: pd.Series,
    low: pd.Series,
    high: pd.Series,
    one_step: pd.Series,
    model_label: str,
    coverage_label: str,
    output: Path,
) -> Path:
    fig, ax = plt.subplots(figsize=(12, 5.5))
    history = train.iloc[-24:]
    ax.plot(history.index, history, color="#9ca3af", linewidth=1.8, label="Ventas reales (últimos 24 meses de entrenamiento)")
    ax.plot(test.index, test, color="#111827", linewidth=2.2, marker="o", markersize=4, label="Ventas reales (2 años de prueba)")
    ax.fill_between(forecast.index, low, high, color="#2563eb", alpha=0.18, label=f"Rango de variabilidad ({coverage_label})")
    ax.plot(forecast.index, forecast, color="#2563eb", linewidth=2, label=f"Predicción recursiva de 24 meses ({model_label})")
    ax.plot(one_step.index, one_step, color="#ea580c", linewidth=1.4, linestyle="--", label="Predicción un mes por delante")
    ax.axvline(test.index[0], color="#6b7280", linestyle=":", linewidth=1)
    ax.text(test.index[0], ax.get_ylim()[0], "  inicio de la prueba", va="bottom", ha="left", fontsize=9, color="#6b7280")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"${value / 1000:,.0f}k"))
    ax.set_ylabel("Ventas mensuales consolidadas (USD)")
    ax.set_title("Brasaland: predicción de ventas vs. datos reales de los 2 años de prueba")
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left", fontsize=9, frameon=False)
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)
    return output


def plot_decomposition(decomposition, output: Path) -> Path:
    """Cuatro paneles: serie observada con su tendencia, tendencia, estacionalidad y residuo (solo entrenamiento)."""
    observed, trend = decomposition.observed, decomposition.trend
    seasonal_pct = (decomposition.seasonal - 1) * 100
    residual_pct = (decomposition.residual - 1) * 100
    fig, axes = plt.subplots(4, 1, figsize=(12, 10), sharex=True)
    money = FuncFormatter(lambda value, _: f"${value / 1000:,.0f}k")
    percent = FuncFormatter(lambda value, _: f"{value:+.0f} %")

    axes[0].plot(observed.index, observed, color="#111827", linewidth=1.6, label="Ventas reales")
    axes[0].plot(trend.index, trend, color="#2563eb", linewidth=2.2, label="Tendencia")
    axes[0].set_title("Serie observada y tendencia")
    axes[0].yaxis.set_major_formatter(money)
    axes[0].legend(loc="upper left", frameon=False, fontsize=9)

    axes[1].plot(trend.index, trend, color="#2563eb", linewidth=2.2)
    growth = decomposition.summary["trend"]["annual_growth_pct"]
    axes[1].set_title(f"Tendencia: crecimiento medio de {growth:.1f} % anual")
    axes[1].yaxis.set_major_formatter(money)

    axes[2].plot(seasonal_pct.index, seasonal_pct, color="#ea580c", linewidth=1.8)
    axes[2].axhline(0, color="#6b7280", linewidth=0.8)
    axes[2].set_title("Estacionalidad: diferencia de cada mes respecto a un mes normal")
    axes[2].yaxis.set_major_formatter(percent)

    axes[3].bar(residual_pct.index, residual_pct, width=20, color="#6b7280")
    axes[3].axhline(0, color="#111827", linewidth=0.8)
    axes[3].set_title(f"Residuo: lo que no explican ni la tendencia ni la estacionalidad (desviación {decomposition.summary['residual']['std_pct']:.1f} %)")
    axes[3].yaxis.set_major_formatter(percent)

    for ax in axes:
        ax.grid(alpha=0.25)
    fig.suptitle("Brasaland: descomposición de las ventas (solo meses de entrenamiento)", fontsize=13)
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)
    return output
