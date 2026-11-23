"""Configuración del módulo de telemetría.

`TELEMETRY_ENDPOINT` es la URL a la que, en la Fase 3 del roadmap, el backend
reenviará los eventos (hoy el stub solo los registra en el log). Se declara ya
para fijar el contrato de configuración, pero todavía no se usa.
"""
from __future__ import annotations

import os

DEFAULT_TELEMETRY_ENDPOINT = "http://localhost:8000/telemetry/events"


def get_telemetry_endpoint() -> str:
    return os.getenv("TELEMETRY_ENDPOINT", DEFAULT_TELEMETRY_ENDPOINT)
