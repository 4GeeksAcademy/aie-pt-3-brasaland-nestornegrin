"""TTLCache: expiración, invalidación, límite de memoria y carreras."""

import pytest

from app.cache import TTLCache


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_cache(ttl=30, max_entries=3):
    clock = FakeClock()
    return TTLCache(ttl, max_entries=max_entries, clock=clock), clock


def test_second_read_is_a_hit_and_does_not_recompute():
    cache, _ = make_cache()
    calls = []

    first = cache.get_or_compute("k", lambda: calls.append(1) or "value")
    second = cache.get_or_compute("k", lambda: calls.append(1) or "other")

    assert first == ("value", False)
    assert second == ("value", True)
    assert len(calls) == 1
    assert (cache.hits, cache.misses) == (1, 1)


def test_entry_expires_after_the_ttl():
    cache, clock = make_cache(ttl=30)
    cache.get_or_compute("k", lambda: "old")

    clock.now += 29.9
    assert cache.get_or_compute("k", lambda: "new") == ("old", True)

    clock.now += 0.2  # 30,1 s desde que se guardó
    assert cache.get_or_compute("k", lambda: "new") == ("new", False)


def test_invalidate_drops_every_entry():
    cache, _ = make_cache()
    cache.get_or_compute("a", lambda: 1)
    cache.get_or_compute("b", lambda: 2)

    cache.invalidate()

    assert len(cache) == 0
    assert cache.get_or_compute("a", lambda: 3) == (3, False)


def test_a_computation_that_started_before_an_invalidation_is_not_stored():
    """Lectura lenta + escritura en medio: guardar el resultado dejaría un
    dato viejo con un TTL nuevo."""
    cache, _ = make_cache()

    def slow_read_interrupted_by_a_write():
        cache.invalidate()  # alguien escribe mientras esta lectura calcula
        return "valor leído antes de la escritura"

    value, hit = cache.get_or_compute("k", slow_read_interrupted_by_a_write)

    assert (value, hit) == ("valor leído antes de la escritura", False)
    assert len(cache) == 0
    assert cache.get_or_compute("k", lambda: "dato fresco") == ("dato fresco", False)


def test_max_entries_evicts_expired_entries_first_then_the_oldest():
    cache, clock = make_cache(ttl=30, max_entries=2)
    cache.get_or_compute("a", lambda: "a")
    clock.now += 10
    cache.get_or_compute("b", lambda: "b")

    cache.get_or_compute("c", lambda: "c")  # lleno y nada caducado: sale la más antigua (a)

    assert len(cache) == 2
    assert cache.get_or_compute("b", lambda: "b2") == ("b", True)
    assert cache.get_or_compute("a", lambda: "a2") == ("a2", False)


def test_a_ttl_of_zero_or_less_is_rejected():
    with pytest.raises(ValueError):
        TTLCache(0)
    with pytest.raises(ValueError):
        TTLCache(-5)
