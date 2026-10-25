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
