"""Carga, validación y split temporal del dataset de ventas de Brasaland.

El dataset (`data/raw/brasaland_sales.csv`) es el provisto por el curso y NO se modifica nunca:
este módulo solo lo lee, valida sus reglas de negocio y lo divide por fecha.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_PATH = REPO_ROOT / "data" / "raw" / "brasaland_sales.csv"

TARGET = "revenue_usd"
MARKET = "consolidated"
REQUIRED_COLUMNS = ("month", "revenue_usd", "covers_served", "avg_ticket_usd", "market")

# Regla del ticket: los primeros 8 años entrenan y los 2 años más recientes comprueban.
TRAIN_YEARS = 8
TEST_YEARS = 2


class SalesDataError(ValueError):
    """El dataset incumple una regla de negocio (columnas, meses, signos...)."""


class SplitError(ValueError):
    """El split entrenamiento/prueba no respeta la regla 8 años / 2 años."""


def file_sha256(path: Path | str = DEFAULT_DATA_PATH) -> str:
    """Huella del archivo original: demuestra en el informe que el dataset no se alteró."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _detect_separator(path: Path) -> str:
    """El CSV del curso usa comas, pero algunas copias llegan con tabuladores: se admiten ambos."""
    with open(path, encoding="utf-8-sig") as handle:
        header = handle.readline()
    return "\t" if header.count("\t") > header.count(",") else ","


def validate_sales(frame: pd.DataFrame) -> pd.DataFrame:
    """Valida las restricciones del briefing y devuelve la serie consolidada indexada por mes."""
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise SalesDataError(f"Faltan columnas obligatorias: {', '.join(missing)}")

    data = frame.loc[frame["market"] == MARKET, list(REQUIRED_COLUMNS)].copy()
    if data.empty:
        raise SalesDataError(f"No hay filas con market='{MARKET}'")
    if data.isna().any().any():
        raise SalesDataError("El dataset contiene valores nulos en las filas consolidadas")

    data["month"] = pd.to_datetime(data["month"], format="%Y-%m-%d")
    if not (data["month"].dt.day == 1).all():
        raise SalesDataError("Todas las fechas deben ser el primer día del mes (YYYY-MM-01)")
    if data["month"].duplicated().any():
        raise SalesDataError("Hay meses duplicados")

    data = data.sort_values("month").set_index("month")
    expected = pd.date_range(data.index.min(), data.index.max(), freq="MS")
    if len(expected) != len(data):
        gaps = expected.difference(data.index)
        raise SalesDataError(f"Faltan meses en la serie: {[d.strftime('%Y-%m') for d in gaps]}")
    if (data[TARGET] <= 0).any():
        raise SalesDataError("revenue_usd debe ser positivo en todos los meses")
    data.index.freq = pd.offsets.MonthBegin(1)  # la serie ya es continua: se declara su frecuencia mensual
    return data.drop(columns=["market"])


def load_sales(path: Path | str = DEFAULT_DATA_PATH) -> pd.DataFrame:
    """Lee el CSV original y devuelve el DataFrame consolidado ya validado."""
    path = Path(path)
    frame = pd.read_csv(path, sep=_detect_separator(path))
    return validate_sales(frame)


def split_train_test(
    data: pd.DataFrame, train_years: int = TRAIN_YEARS, test_years: int = TEST_YEARS
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Divide por fecha: primeros `train_years` años -> entrenamiento; `test_years` más recientes -> prueba.

    Es un corte temporal estricto (nunca aleatorio): ningún mes de prueba es anterior a uno de entrenamiento
    y ambos conjuntos son disjuntos.
    """
    n_train, n_test = 12 * train_years, 12 * test_years
    if len(data) < n_train + n_test:
        raise SplitError(f"Se necesitan al menos {n_train + n_test} meses y hay {len(data)}")

    train, test = data.iloc[:n_train], data.iloc[-n_test:]
    if train.index.max() >= test.index.min():
        raise SplitError("El entrenamiento y la prueba se solapan en el tiempo")
    if not train.index.intersection(test.index).empty:
        raise SplitError("Hay meses compartidos entre entrenamiento y prueba")
    return train, test
