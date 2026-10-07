"""Caché en proceso con expiración (TTL), segura entre hilos.

Diseño y decisiones (el razonamiento completo está en CACHING_REPORT.md):

- TTL obligatorio: ningún valor vive para siempre. El TTL es la red de
  seguridad para cambios que NO pasan por este proceso (otro worker de
  uvicorn, un script de seed que escribe en el mismo fichero).
- Invalidación explícita: quien escribe llama a ``invalidate()``, así que
  dentro de este proceso una escritura se ve en la siguiente lectura, sin
  esperar al TTL.
- Sin carreras: ``invalidate()`` sube un contador de versión. Si una lectura
  empezó antes de la invalidación y termina después, su resultado se devuelve
  a quien lo pidió pero NO se guarda (sería un dato viejo con TTL nuevo).
- Memoria acotada: ``max_entries`` limita las claves distintas (p. ej. las
  combinaciones de filtros); al llenarse se descartan primero las caducadas y
  después la más antigua.
- NO usar para datos privados o de sesión con una clave compartida: la clave
  debe incluir al usuario si la respuesta depende de él.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Hashable
from threading import Lock
from typing import Generic, TypeVar

V = TypeVar("V")


class TTLCache(Generic[V]):
    def __init__(self, ttl_seconds: float, max_entries: int = 64, clock: Callable[[], float] = time.monotonic) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds debe ser mayor que cero: una caché sin expiración sirve datos obsoletos para siempre")
        if max_entries < 1:
            raise ValueError("max_entries debe ser al menos 1")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._entries: dict[Hashable, tuple[float, V]] = {}  # clave -> (instante de caducidad, valor)
        self._version = 0
        self._lock = Lock()
        self.hits = 0
        self.misses = 0

    def get_or_compute(self, key: Hashable, factory: Callable[[], V]) -> tuple[V, bool]:
        """Devuelve ``(valor, hubo_acierto)``. En un fallo ejecuta ``factory``
        fuera del cerrojo: dos peticiones simultáneas pueden calcular el
        mismo valor, a cambio de no bloquear al resto de claves."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry[0] > self._clock():
                self.hits += 1
                return entry[1], True
            self.misses += 1
            version = self._version
        value = factory()
        with self._lock:
            if version == self._version:  # nadie invalidó mientras calculábamos
                self._store(key, value)
        return value, False

    def invalidate(self) -> None:
        """Descarta todo y marca como obsoletos los cálculos en curso."""
        with self._lock:
            self._entries.clear()
            self._version += 1

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _store(self, key: Hashable, value: V) -> None:
        now = self._clock()
        if key not in self._entries and len(self._entries) >= self.max_entries:
            expired = [k for k, (expires_at, _) in self._entries.items() if expires_at <= now]
            for k in expired:
                del self._entries[k]
            if len(self._entries) >= self.max_entries:
                del self._entries[min(self._entries, key=lambda k: self._entries[k][0])]
        self._entries[key] = (now + self.ttl_seconds, value)
