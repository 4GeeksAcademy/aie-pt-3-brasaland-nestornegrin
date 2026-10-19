"""Último resultado del análisis de incidencias.

Antes vivía en una variable global del proceso de FastAPI (`_latest_result`). Con el análisis ejecutándose en un
worker —otro proceso— esa variable no sirve: el worker lo guarda en Redis y `GET /api/incidents/results/export`
lo lee de ahí. Sigue siendo «el último resultado de cualquiera», igual que antes.
"""
from __future__ import annotations

import json
from typing import Any

import redis

from services.async_tasks import config

LATEST_RESULT_KEY = "brasaland:incidents:latest_result"


def _client() -> redis.Redis:
    return redis.Redis.from_url(config.REDIS_URL, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)


def store_latest(payload: dict[str, Any]) -> None:
    _client().set(LATEST_RESULT_KEY, json.dumps(payload))


def load_latest() -> dict[str, Any] | None:
    raw = _client().get(LATEST_RESULT_KEY)
    return json.loads(raw) if raw else None
