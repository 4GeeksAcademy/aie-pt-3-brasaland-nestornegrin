"""Configuración del pipeline «Desempeño de Inventario por Restaurante».

Valores de `data/pipelines/PIPELINE_DESIGN.md` §8.3 (bloque `inventory-kpi-settings`). En producción
irían en un Block de Prefect; en esta versión son constantes con sobrescritura por variable de entorno,
para poder correr el pipeline en un Codespace sin servidor de Prefect configurado.
"""
from __future__ import annotations

import os
from datetime import timedelta

from data.process.business_kpis import DEFAULT_CRITICAL_THRESHOLD, DEFAULT_LOW_THRESHOLD


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


PIPELINE_NAME = "inventory_performance_daily"
# Cambia cuando cambia la lógica de cálculo: queda en `pipeline_runs.code_version` para poder explicar
# por qué los números de dos corridas difieren (diseño §7.2) y forma parte de la clave de caché.
CODE_VERSION = "inventory-performance/1.0.0"

LOW_THRESHOLD = float(os.getenv("INVENTORY_LOW_THRESHOLD", DEFAULT_LOW_THRESHOLD))
CRITICAL_THRESHOLD = float(os.getenv("INVENTORY_CRITICAL_THRESHOLD", DEFAULT_CRITICAL_THRESHOLD))
LOOKBACK_DAYS = _int("INVENTORY_LOOKBACK_DAYS", 3)  # días locales recalculados siempre (K6 depende del stock)
WATERMARK_OVERLAP = _int("INVENTORY_WATERMARK_OVERLAP", 2000)  # ids que se releen por si un commit tardío llega fuera de orden
PAGE_SIZE = _int("INVENTORY_PAGE_SIZE", 5000)  # filas por página en la extracción

HEARTBEAT_TIMEOUT = timedelta(minutes=10)  # una corrida `running` sin latido más tiempo que esto se marca `crashed`
STALE_AFTER = timedelta(hours=26)  # si la última corrida exitosa es más vieja, `status` avisa de que el cron no corrió
CACHE_EXPIRATION = timedelta(hours=1)  # requisito del ticket: lo que corrió bien en la última hora no se repite

CRON_SCHEDULE = os.getenv("INVENTORY_PIPELINE_CRON", "0 10 * * *")  # 10:00 UTC = 05:00 Bogotá (diseño §2.2)
MAX_RANGE_DAYS = 366  # tope de un rango manual / consulta de KPIs
