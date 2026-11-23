"""Endpoints de `services/reporting/` (diseño §9.1): contrato, autenticación, errores y reglas de arquitectura.

Aquí la capa `data/pipelines/inventory_performance/api.py` se sustituye por dobles: lo que se prueba es el
CONTRATO HTTP (códigos, formas de respuesta, que cada handler delega en `data/pipelines/` sin duplicar lógica).
El comportamiento real contra Postgres está en `test_pipeline_integration.py` (opt-in).
"""
from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest

from data.pipelines.inventory_performance import api as pipeline_api

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE = "/reporting/inventory-performance"

KPI_ITEM = {
    "report_date": "2026-10-05", "restaurant": "Brasaland El Poblado", "country": "Colombia", "outbound_orders": 3, "units_issued": 10.0,
    "spoilage_units": 3.0, "spoilage_rate_pct": 30.0, "stock_alerts_low": 1, "stock_alerts_critical": 2, "validation_failures": 1,
    "validation_rejection_rate_pct": 25.0, "ingredients_at_risk_eod": 2, "ingredients_critical_eod": 1, "telemetry_coverage_pct": 75.0,
    "events_deduplicated": 0, "capture_health": "ok", "revision": 1,
}


@pytest.fixture
def headers(auth_headers):
    return auth_headers()


# ----------------------------------------------------------------- autenticación
@pytest.mark.parametrize("method,path", [("get", "/status"), ("post", "/runs"), ("get", "/kpis")])
def test_every_reporting_endpoint_requires_authentication(client, method, path):
    assert getattr(client, method)(BASE + path).status_code == 401


# ----------------------------------------------------------------- (1) estado
def test_status_returns_last_run_metadata(client, headers, monkeypatch):
    status = {
        "last_run": {"run_id": "r-1", "status": "completed", "started_at": "2026-10-14T10:00:00Z", "finished_at": "2026-10-14T10:00:05Z", "rows_extracted": 12},
        "last_success_at": "2026-10-14T10:00:05Z", "watermark_lag": 4, "is_running": False, "active_run_id": None, "is_stale": False,
        "capture_health": {"ok": 3, "real_zero": 39},
    }
    monkeypatch.setattr(pipeline_api, "get_pipeline_status", lambda engine: status)
    response = client.get(f"{BASE}/status", headers=headers)
    assert response.status_code == 200
    assert response.json() == status


def test_status_before_any_run_has_no_last_run(client, headers, monkeypatch):
    empty = {"last_run": None, "last_success_at": None, "watermark_lag": 0, "is_running": False, "active_run_id": None, "is_stale": True, "capture_health": {}}
    monkeypatch.setattr(pipeline_api, "get_pipeline_status", lambda engine: empty)
    assert client.get(f"{BASE}/status", headers=headers).json()["last_run"] is None


# ----------------------------------------------------------------- (2) disparo manual
def test_trigger_run_delegates_to_the_pipeline_and_returns_202(client, headers, monkeypatch):
    calls = []
    monkeypatch.setattr(
        pipeline_api, "trigger_inventory_performance_run",
        lambda engine, triggered_by, date_from=None, date_to=None: calls.append((triggered_by, date_from, date_to)) or {"run_id": "abc", "status": "queued"},
    )
    response = client.post(f"{BASE}/runs", json={"date_from": "2026-10-01", "date_to": "2026-10-03"}, headers=headers)
    assert response.status_code == 202
    assert response.json() == {"run_id": "abc", "status": "queued"}
    assert calls == [(1, date(2026, 10, 1), date(2026, 10, 3))]  # quién la disparó + el rango, sin lógica propia


def test_trigger_run_without_body_is_an_incremental_run(client, headers, monkeypatch):
    calls = []
    monkeypatch.setattr(
        pipeline_api, "trigger_inventory_performance_run",
        lambda engine, triggered_by, date_from=None, date_to=None: calls.append((date_from, date_to)) or {"run_id": "abc", "status": "queued"},
    )
    assert client.post(f"{BASE}/runs", headers=headers).status_code == 202
    assert calls == [(None, None)]


def test_trigger_run_returns_409_with_the_active_run_id(client, headers, monkeypatch):
    def busy(engine, triggered_by, date_from=None, date_to=None):
        raise pipeline_api.PipelineAlreadyRunning("run-in-progress")

    monkeypatch.setattr(pipeline_api, "trigger_inventory_performance_run", busy)
    response = client.post(f"{BASE}/runs", headers=headers)
    assert response.status_code == 409
    assert response.json()["run_id"] == "run-in-progress" and "detail" in response.json()


def test_trigger_run_rejects_an_invalid_range_with_400(client, headers, monkeypatch):
    def invalid(engine, triggered_by, date_from=None, date_to=None):
        raise ValueError("date_from no puede ser posterior a date_to")

    monkeypatch.setattr(pipeline_api, "trigger_inventory_performance_run", invalid)
    response = client.post(f"{BASE}/runs", json={"date_from": "2026-10-05", "date_to": "2026-10-01"}, headers=headers)
    assert response.status_code == 400 and "posterior" in response.json()["detail"]
    assert client.post(f"{BASE}/runs", json={"date_from": "no-es-fecha"}, headers=headers).status_code == 400


# ----------------------------------------------------------------- (3) KPIs
def test_kpis_returns_the_rows_of_the_destination_table_and_passes_filters(client, headers, monkeypatch):
    seen = []
    monkeypatch.setattr(
        pipeline_api, "query_inventory_kpis",
        lambda engine, filters: seen.append(filters) or {"items": [KPI_ITEM], "generated_at": "2026-10-14T10:00:00Z"},
    )
    response = client.get(
        f"{BASE}/kpis", params={"from": "2026-10-01", "to": "2026-10-07", "restaurant": "Brasaland El Poblado", "country": "Colombia", "granularity": "week"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "generated_at"}
    assert body["items"][0] == KPI_ITEM  # el contrato que consumirá el dashboard
    assert seen == [pipeline_api.KpiFilters(date(2026, 10, 1), date(2026, 10, 7), "Brasaland El Poblado", "Colombia", "week")]


def test_kpis_defaults_to_daily_granularity(client, headers, monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline_api, "query_inventory_kpis", lambda engine, filters: seen.append(filters) or {"items": [], "generated_at": "x"})
    assert client.get(f"{BASE}/kpis", headers=headers).status_code == 200
    assert seen[0].granularity == "day" and seen[0].date_from is None


@pytest.mark.parametrize("params", [{"granularity": "month"}, {"from": "ayer"}])
def test_kpis_rejects_invalid_parameters_with_400(client, headers, params):
    assert client.get(f"{BASE}/kpis", params=params, headers=headers).status_code == 400


def test_kpis_maps_invalid_filters_to_400(client, headers, monkeypatch):
    def invalid(engine, filters):
        raise pipeline_api.InvalidKpiFilters("from no puede ser posterior a to")

    monkeypatch.setattr(pipeline_api, "query_inventory_kpis", invalid)
    assert client.get(f"{BASE}/kpis", headers=headers).status_code == 400


# ----------------------------------------------------------------- reglas de arquitectura (diseño §9.3 y ticket)
def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    return names


def test_data_never_imports_from_services_or_the_api_app():
    """`data/pipelines/` no depende de `services/` (diseño §9.3): la dirección es services → data, nunca al revés."""
    offenders = {
        str(path.relative_to(REPO_ROOT)): sorted(name for name in _imports(path) if name.split(".")[0] in {"services", "app"})
        for path in (REPO_ROOT / "data").rglob("*.py")
    }
    assert {file: names for file, names in offenders.items() if names} == {}


def test_reporting_is_separate_from_telemetry_and_holds_no_etl_logic():
    imports = _imports(REPO_ROOT / "services" / "reporting" / "router.py")
    assert not any(name.startswith("app.telemetry") for name in imports)  # no comparte código con /telemetry/report
    assert not any(name.split(".")[0] in {"pandas", "prefect"} for name in imports)  # solo delega en data/pipelines
    assert any(name.startswith("data.pipelines") for name in imports)


def test_pipeline_does_not_write_to_telemetry_events_nor_import_analysis():
    """El pipeline solo LEE `telemetry_events` y no toca `analysis.py` (requisito no negociable del ticket)."""
    sql_files = [REPO_ROOT / "data" / "pipelines" / "inventory_performance" / name for name in ("queries.py", "db.py")]
    for path in sql_files:
        source = path.read_text(encoding="utf-8").upper()
        for verb in ("INSERT INTO PUBLIC.TELEMETRY_EVENTS", "UPDATE PUBLIC.TELEMETRY_EVENTS", "DELETE FROM PUBLIC.TELEMETRY_EVENTS", "TRUNCATE"):
            assert verb not in source, f"{path.name} no debe contener {verb}"
    for path in (REPO_ROOT / "data").rglob("*.py"):
        assert not any(name.startswith("app.telemetry") for name in _imports(path))
