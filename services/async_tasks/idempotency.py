"""Idempotencia: la misma operación (misma clave) nunca produce su efecto dos veces.

Tres claves en Redis por operación (`key` = p. ej. `password-reset:42`):
  idem:enq:<key>   → task_id de la primera vez que se ENCOLÓ. Un segundo encolado con la misma clave no publica nada
                     y devuelve ese mismo task_id (protege frente a doble clic, reintentos del cliente y reenvíos).
  idem:done:<key>  → la operación terminó CON ÉXITO. Antes de procesar, el worker lo comprueba: si existe, no repite el efecto
                     (protege frente a entregas duplicadas del broker, p. ej. visibility timeout o ACK tardío).
  idem:lock:<key>  → alguien la está procesando ahora mismo (TTL = visibility timeout: si el worker muere, se libera sola).

Si el worker envía el email pero muere antes de escribir `done`, el reintento volvería a enviarlo: por eso la clave de
idempotencia también viaja al proveedor (Resend la deduplica por su cuenta). Dos barreras, no una.
"""
from __future__ import annotations

import logging
import threading
from typing import Literal, Protocol

from services.async_tasks import config

logger = logging.getLogger(__name__)

Begin = Literal["acquired", "done", "busy"]


class IdempotencyStore(Protocol):
    def claim_enqueue(self, key: str, task_id: str) -> str | None: ...
    def release_enqueue(self, key: str) -> None: ...
    def begin(self, key: str) -> Begin: ...
    def complete(self, key: str) -> None: ...
    def release(self, key: str) -> None: ...
    def record_attempt(self, task_id: str, attempt: int) -> None: ...
    def attempts(self, task_id: str) -> int | None: ...


class RedisIdempotencyStore:
    def __init__(self, url: str | None = None) -> None:
        self._url = url or config.REDIS_URL
        self._client = None

    @property
    def redis(self):
        if self._client is None:
            import redis

            self._client = redis.Redis.from_url(self._url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True)
        return self._client

    def claim_enqueue(self, key: str, task_id: str) -> str | None:
        if self.redis.set(f"idem:enq:{key}", task_id, nx=True, ex=config.IDEMPOTENCY_TTL_SECONDS):
            return None
        return self.redis.get(f"idem:enq:{key}") or task_id

    def release_enqueue(self, key: str) -> None:
        self.redis.delete(f"idem:enq:{key}")

    def begin(self, key: str) -> Begin:
        if self.redis.exists(f"idem:done:{key}"):
            return "done"
        if self.redis.set(f"idem:lock:{key}", "1", nx=True, ex=config.VISIBILITY_TIMEOUT_SECONDS):
            return "acquired"
        return "busy"

    def complete(self, key: str) -> None:
        self.redis.set(f"idem:done:{key}", "1", ex=config.IDEMPOTENCY_TTL_SECONDS)
        self.redis.delete(f"idem:lock:{key}")

    def release(self, key: str) -> None:
        self.redis.delete(f"idem:lock:{key}")

    def record_attempt(self, task_id: str, attempt: int) -> None:
        self.redis.set(f"task:attempts:{task_id}", attempt, ex=config.RESULT_TTL_SECONDS)

    def attempts(self, task_id: str) -> int | None:
        value = self.redis.get(f"task:attempts:{task_id}")
        return int(value) if value is not None else None


class MemoryIdempotencyStore:
    """Mismo contrato en memoria: para pruebas y desarrollo sin Redis."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._enqueued: dict[str, str] = {}
        self._done: set[str] = set()
        self._locked: set[str] = set()
        self._attempts: dict[str, int] = {}

    def claim_enqueue(self, key: str, task_id: str) -> str | None:
        with self._lock:
            if key in self._enqueued:
                return self._enqueued[key]
            self._enqueued[key] = task_id
            return None

    def release_enqueue(self, key: str) -> None:
        with self._lock:
            self._enqueued.pop(key, None)

    def begin(self, key: str) -> Begin:
        with self._lock:
            if key in self._done:
                return "done"
            if key in self._locked:
                return "busy"
            self._locked.add(key)
            return "acquired"

    def complete(self, key: str) -> None:
        with self._lock:
            self._done.add(key)
            self._locked.discard(key)

    def release(self, key: str) -> None:
        with self._lock:
            self._locked.discard(key)

    def record_attempt(self, task_id: str, attempt: int) -> None:
        with self._lock:
            self._attempts[task_id] = attempt

    def attempts(self, task_id: str) -> int | None:
        with self._lock:
            return self._attempts.get(task_id)


_store: IdempotencyStore | None = None


def get_store() -> IdempotencyStore:
    global _store
    if _store is None:
        _store = RedisIdempotencyStore()
    return _store


def set_store(store: IdempotencyStore | None) -> None:
    """Inyecta el almacén (tests). `None` vuelve al de Redis."""
    global _store
    _store = store
