"""Reporte técnico: funciones de análisis (Pandas) y `GET /telemetry/report`."""
import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlmodel import Session

from app.database import engine
from app.telemetry import analysis, report
from app.telemetry.orm import TelemetryEventRecord

UTC = timezone.utc
DAY1 = datetime(2026, 10, 5, tzinfo=UTC)
DAY2 = datetime(2026, 10, 6, tzinfo=UTC)
START = datetime(2026, 10, 5, tzinfo=UTC)
END = datetime(2026, 10, 8, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean():
    with Session(engine) as session:
        if engine.dialect.name == "postgresql":
            session.execute(text("TRUNCATE telemetry_events"))
        else:
            session.execute(text("DELETE FROM telemetry_events"))
        session.commit()
    report.report_cache.clear()
    yield
    report.report_cache.clear()


def _add(*events):
    """Inserta eventos ya validados: (event_type, timestamp, tags, service)."""
    with Session(engine) as session:
        for event_type, timestamp, tags, *rest in events:
            session.add(
                TelemetryEventRecord(
                    event_id=uuid4(),
                    event_type=event_type,
                    timestamp=timestamp,
                    service=rest[0] if rest else "frontend",
                    user_id="1",
                    session_id="s-1",
                    tags=tags,
                )
            )
        session.commit()


def _run(metric, start=START, end=END):
    with Session(engine) as session:
        return metric(session, start, end)


# ------------------------------------------------------------------ métricas
def test_events_per_day_groups_by_utc_day_and_service():
    _add(
        ("web_vital_measured", datetime(2026, 10, 5, 23, 30, tzinfo=UTC), {}),
        ("web_vital_measured", datetime(2026, 10, 6, 0, 30, tzinfo=UTC), {}),  # otro día UTC
        ("incident_created", datetime(2026, 10, 6, 9, 0, tzinfo=UTC), {}, "backend"),
    )
    assert _run(analysis.events_per_day) == [
        {"date": "2026-10-05", "service": "frontend", "events": 1},
        {"date": "2026-10-06", "service": "backend", "events": 1},
        {"date": "2026-10-06", "service": "frontend", "events": 1},
    ]


def test_event_type_distribution_orders_by_volume_and_gives_share():
    _add(
        *[("web_vital_measured", DAY1 + timedelta(minutes=i), {}) for i in range(3)],
        ("login_failed", DAY1, {}),
    )
    assert _run(analysis.event_type_distribution) == [
        {"event_type": "web_vital_measured", "events": 3, "share_pct": 75.0},
        {"event_type": "login_failed", "events": 1, "share_pct": 25.0},
    ]


def test_error_rate_counts_only_technical_errors_over_the_days_total():
    _add(
        ("frontend_error_captured", DAY1 + timedelta(hours=1), {}),
        ("network_request_failed", DAY1 + timedelta(hours=2), {}),
        ("inventory_validation_failed", DAY1 + timedelta(hours=3), {}),  # regla de negocio: no es error técnico
        ("web_vital_measured", DAY1 + timedelta(hours=4), {}),
        ("web_vital_measured", DAY2 + timedelta(hours=1), {}),  # día sin errores: no aparece
    )
    assert _run(analysis.error_rate_by_type) == [
        {"date": "2026-10-05", "event_type": "frontend_error_captured", "errors": 1, "total_events": 4, "error_rate_pct": 25.0},
        {"date": "2026-10-05", "event_type": "network_request_failed", "errors": 1, "total_events": 4, "error_rate_pct": 25.0},
    ]


def test_latency_by_day_aggregates_per_route_and_drops_rows_without_dimension():
    route = {"routeTemplate": "/inventory/products"}
    _add(
        *[("api_latency_recorded", DAY1 + timedelta(minutes=i), {**route, "durationMs": ms}) for i, ms in enumerate((100, 200, 300, 400))],
        ("api_latency_recorded", DAY1, {"routeTemplate": "/suppliers", "durationMs": 50}),
        ("api_latency_recorded", DAY1, {"durationMs": 999}),  # sin ruta: se descarta
        ("api_latency_recorded", DAY1, {"routeTemplate": "/suppliers"}),  # sin duración: se descarta
    )
    assert _run(analysis.latency_by_day) == [
        {"date": "2026-10-05", "routeTemplate": "/inventory/products", "samples": 4, "mean_ms": 250.0, "p95_ms": 385.0, "max_ms": 400.0},
        {"date": "2026-10-05", "routeTemplate": "/suppliers", "samples": 1, "mean_ms": 50.0, "p95_ms": 50.0, "max_ms": 50.0},
    ]


def test_auth_failure_rate_is_failed_over_total_attempts_per_day():
    _add(
        ("login_failed", DAY1 + timedelta(hours=1), {}),
        *[("login_succeeded", DAY1 + timedelta(hours=2 + i), {}) for i in range(3)],
        ("login_failed", DAY2 + timedelta(hours=1), {}),
        ("login_failed", DAY2 + timedelta(hours=2), {}),
        ("web_vital_measured", DAY2, {}),  # no es un intento de login
    )
    assert _run(analysis.auth_failure_rate) == [
        {"date": "2026-10-05", "attempts": 4, "failures": 1, "failure_rate_pct": 25.0},
        {"date": "2026-10-06", "attempts": 2, "failures": 2, "failure_rate_pct": 100.0},
    ]


def test_window_is_start_inclusive_end_exclusive():
    _add(
        ("web_vital_measured", START, {}),  # justo en `start`: entra
        ("web_vital_measured", END, {}),  # justo en `end`: no entra
        ("web_vital_measured", START - timedelta(seconds=1), {}),
    )
    assert _run(analysis.event_type_distribution) == [{"event_type": "web_vital_measured", "events": 1, "share_pct": 100.0}]


def test_metrics_are_pure_json_serializable_and_empty_window_is_safe():
    _add(
        ("login_failed", DAY1, {}),
        ("api_latency_recorded", DAY1, {"routeTemplate": "/x", "durationMs": 10}),
        ("network_request_failed", DAY1, {}),
    )
    first = _run(analysis.build_metrics)
    assert _run(analysis.build_metrics) == first  # mismos parámetros → mismo resultado
    json.dumps(first)  # tipos nativos de Python (sin numpy)
    assert set(first) == {"events_per_day", "event_type_distribution", "error_rate_by_type", "latency_by_day", "auth_failure_rate"}

    empty = _run(analysis.build_metrics, datetime(2030, 1, 1, tzinfo=UTC), datetime(2030, 1, 2, tzinfo=UTC))
    assert all(value == [] for value in empty.values())


def test_analysis_module_has_no_loops():
    """Regla del ticket: solo operaciones de Pandas, ningún bucle ni comprensión."""
    tree = ast.parse(Path(analysis.__file__).read_text())
    loops = [type(node).__name__ for node in ast.walk(tree) if isinstance(node, (ast.For, ast.While, ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp))]
    assert loops == []


# ------------------------------------------------------------------ período
def test_resolve_period_defaults_to_last_seven_days_in_utc():
    now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
    start, end = report.resolve_period(None, None, now=lambda: now)
    assert (start, end) == (now - timedelta(days=7), now)
    # sin zona horaria = UTC; con offset se convierte a UTC
    start, end = report.resolve_period(datetime(2026, 10, 1), datetime(2026, 10, 2, 2, 0, tzinfo=timezone(timedelta(hours=2))))
    assert (start, end) == (datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, 0, 0, tzinfo=UTC))


# ------------------------------------------------------------------ caché
def test_cache_ttl_with_fake_clock():
    now = [1000.0]
    cache = report.ReportCache(ttl_seconds=60, clock=lambda: now[0])
    calls = []

    def compute():
        calls.append(1)
        return {"n": len(calls)}

    key = ("a", "b")
    assert cache.get_or_compute(key, compute) == ({"n": 1}, False)
    now[0] += 59.9
    assert cache.get_or_compute(key, compute) == ({"n": 1}, True)  # dentro del TTL: no recalcula
    now[0] += 0.2
    assert cache.get_or_compute(key, compute) == ({"n": 2}, False)  # caducó: recalcula
    assert len(calls) == 2


def test_cache_is_bounded():
    cache = report.ReportCache(ttl_seconds=60, clock=lambda: 0.0)
    for i in range(report.CACHE_MAX_ENTRIES + 10):
        cache.get_or_compute((str(i), None), lambda: {})
    assert len(cache._entries) == report.CACHE_MAX_ENTRIES


# ------------------------------------------------------------------ endpoint
def test_report_requires_authentication(client):
    assert client.get("/telemetry/report").status_code == 401


def test_report_structure_default_period_and_cache(client, auth_headers, monkeypatch):
    headers = auth_headers()
    _add(("login_failed", datetime.now(UTC) - timedelta(hours=1), {}))
    calls = []
    real = report.build_metrics
    monkeypatch.setattr(report, "build_metrics", lambda *args: calls.append(args) or real(*args))

    first = client.get("/telemetry/report", headers=headers)
    assert first.status_code == 200
    body = first.json()
    assert set(body) == {"period", "metrics"}
    assert set(body["metrics"]) == {"events_per_day", "event_type_distribution", "error_rate_by_type", "latency_by_day", "auth_failure_rate"}
    assert body["metrics"]["auth_failure_rate"][0]["failures"] == 1
    period_from = datetime.fromisoformat(body["period"]["from"].replace("Z", "+00:00"))
    period_to = datetime.fromisoformat(body["period"]["to"].replace("Z", "+00:00"))
    assert period_to - period_from == timedelta(days=7)  # 7 días por defecto, en UTC
    assert first.headers["X-Cache"] == "MISS"

    second = client.get("/telemetry/report", headers=headers)  # misma combinación (sin parámetros)
    assert second.json() == body
    assert second.headers["X-Cache"] == "HIT"
    assert len(calls) == 1  # el pipeline NO se ejecutó otra vez

    other = client.get("/telemetry/report", params={"start_date": "2026-10-01", "end_date": "2026-10-03T00:00:00Z"}, headers=headers)
    assert other.status_code == 200
    assert other.json()["period"] == {"from": "2026-10-01T00:00:00Z", "to": "2026-10-03T00:00:00Z"}
    assert other.headers["X-Cache"] == "MISS"
    assert len(calls) == 2  # otra combinación → se calcula


def test_report_resolves_the_period_once_for_all_metrics(client, auth_headers, monkeypatch):
    headers = auth_headers()
    seen = []
    monkeypatch.setattr(report, "build_metrics", lambda session, start, end: seen.append((start, end)) or {})
    client.get("/telemetry/report", headers=headers)
    assert len(seen) == 1  # una ventana, un solo cálculo, la misma para todas las métricas


@pytest.mark.parametrize(
    "params",
    [
        {"start_date": "2026-10-05", "end_date": "2026-10-05"},  # vacío
        {"start_date": "2026-10-06", "end_date": "2026-10-05"},  # invertido
        {"start_date": "2026-01-01", "end_date": "2026-10-05"},  # > 90 días
        {"start_date": "no-es-una-fecha"},
    ],
)
def test_report_rejects_invalid_periods(client, auth_headers, params):
    response = client.get("/telemetry/report", params=params, headers=auth_headers())
    assert response.status_code == 400, response.text
