"""Pipeline de desempeño de negocio contra Postgres REAL: resiliencia, idempotencia y endpoints.

⚠️  DESTRUCTIVO: cada test borra el esquema `reporting` y TRUNCA `telemetry_events` y las tablas de inventario.
Por eso es OPT-IN y nunca corre por defecto: exige `PIPELINE_INTEGRATION_TESTS=1` y una `DATABASE_URL` de Postgres
que sea una base de PRUEBAS (jamás la de Supabase con datos reales):

    PIPELINE_INTEGRATION_TESTS=1 DATABASE_URL=postgresql://… python -m pytest tests/test_pipeline_integration.py

Cada test fija una garantía del ticket: tolerancia a fallos parciales, reintentos, caché, idempotencia,
corridas concurrentes y los tres endpoints sobre datos reales de la tabla de destino.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from prefect import task
from prefect.testing.utilities import prefect_test_harness
from sqlalchemy import text
from sqlmodel import Session, select

from app.database import engine
from app.inventory.models import Ingredient, IngredientEntry, IngredientExit
from app.telemetry.orm import TelemetryEventRecord
from data.pipelines import pipeline
from data.pipelines.inventory_performance import api as pipeline_api
from data.pipelines.inventory_performance import db, settings

pytestmark = pytest.mark.skipif(
    os.getenv("PIPELINE_INTEGRATION_TESTS") != "1" or engine.dialect.name != "postgresql",
    reason="Destructivo: requiere PIPELINE_INTEGRATION_TESTS=1 y una DATABASE_URL de Postgres de PRUEBAS",
)

UTC = timezone.utc
POBLADO = "Brasaland El Poblado"
YESTERDAY = datetime.now(UTC).date() - timedelta(days=1)
NOON = datetime.combine(YESTERDAY, datetime.min.time(), tzinfo=UTC).replace(hour=15)  # 10:00 Bogotá: el mismo día local que UTC


# ----------------------------------------------------------------- infraestructura de test
@pytest.fixture(scope="session", autouse=True)
def _prefect_server():
    with prefect_test_harness():
        yield


@pytest.fixture(autouse=True)
def _clean(request, monkeypatch):
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS reporting CASCADE"))
        connection.execute(text("TRUNCATE telemetry_events, ingredient_entries, ingredient_exits, ingredients RESTART IDENTITY CASCADE"))
    db.reset_schema_cache()
    # Una versión de código distinta por test → una clave de caché distinta: ningún test hereda el resultado de otro.
    monkeypatch.setattr(settings, "CODE_VERSION", f"test/{request.node.name}")
    yield


def _event(session: Session, event_type: str, timestamp: datetime, tags: dict, service: str = "frontend") -> None:
    session.add(TelemetryEventRecord(event_id=uuid4(), event_type=event_type, timestamp=timestamp, service=service, user_id="1", session_id="s", tags=tags))


def seed(extra_late_event: bool = False) -> None:
    """Chorizo (merma) y papa en El Poblado: 3 salidas reales, 2 capturadas por telemetría (+ un duplicado)."""
    with Session(engine) as session:
        chorizo, papa = Ingredient(name="Chorizo", sku="CHO-1", restaurant=POBLADO), Ingredient(name="Papa", sku="PAP-1", restaurant=POBLADO)
        session.add_all([chorizo, papa])
        session.commit()
        before = NOON - timedelta(days=1)
        session.add_all([IngredientEntry(ingredient_id=chorizo.id, quantity=40, created_at=before, user_uuid=1), IngredientEntry(ingredient_id=papa.id, quantity=100, created_at=before, user_uuid=1)])
        exits = [
            IngredientExit(ingredient_id=chorizo.id, quantity=10, reason="Merma por vencimiento", created_at=NOON, user_uuid=1),
            IngredientExit(ingredient_id=papa.id, quantity=5, reason="Uso en cocina", created_at=NOON, user_uuid=1),
            IngredientExit(ingredient_id=papa.id, quantity=1, reason="Uso en cocina", created_at=NOON + timedelta(hours=1), user_uuid=1),  # la telemetría no la vio
        ]
        session.add_all(exits)
        session.commit()
        order = lambda exit_row, qty: {"exitId": exit_row.id, "ingredientId": exit_row.ingredient_id, "restaurant": POBLADO, "quantity": qty}  # noqa: E731
        _event(session, "outbound_order_created", NOON, order(exits[0], 10))
        _event(session, "outbound_order_created", NOON, order(exits[0], 10), service="backend")  # misma orden emitida por otro lado → se deduplica
        _event(session, "outbound_order_created", NOON, order(exits[1], 5))
        _event(session, "stock_threshold_triggered", NOON, {"restaurant": POBLADO, "level": "low", "triggeringExitId": exits[0].id})
        _event(session, "inventory_validation_failed", NOON, {"restaurant": POBLADO})
        session.commit()


def add_late_order() -> None:
    """Un evento (y su salida real) que llega DESPUÉS de la primera corrida, para un día ya publicado."""
    with Session(engine) as session:
        papa = session.exec(select(Ingredient).where(Ingredient.sku == "PAP-1")).one()
        late_exit = IngredientExit(ingredient_id=papa.id, quantity=2, reason="Uso en cocina", created_at=NOON + timedelta(hours=2), user_uuid=1)
        session.add(late_exit)
        session.commit()
        _event(session, "outbound_order_created", NOON + timedelta(hours=2), {"exitId": late_exit.id, "ingredientId": papa.id, "restaurant": POBLADO, "quantity": 2})
        session.commit()


def daily() -> dict:
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT * FROM reporting.restaurant_inventory_daily")).mappings().all()
    return {(row["report_date"], row["restaurant"]): dict(row) for row in rows}


def scalar(sql: str):
    with engine.connect() as connection:
        return connection.execute(text(sql)).scalar()


def run(**kwargs):
    return pipeline.inventory_performance_daily_flow(trigger="manual", **kwargs)


# ----------------------------------------------------------------- resultado correcto
def test_pipeline_computes_the_kpis_from_real_rows_and_logs_the_run():
    seed()
    result = run()
    assert result["status"] == "completed"
    poblado = daily()[(YESTERDAY, POBLADO)]
    assert poblado["outbound_orders"] == 2 and float(poblado["units_issued"]) == 15.0  # K1, K2 (el duplicado backend/frontend cuenta una vez)
    assert float(poblado["spoilage_rate_pct"]) == 66.67  # K3: 10 de 15 unidades eran «Merma por vencimiento»
    assert poblado["stock_alerts_low"] == 1 and poblado["validation_failures"] == 1  # K4, rechazos
    assert float(poblado["validation_rejection_rate_pct"]) == 33.33  # K5: 1 ÷ (2 + 1)
    assert (poblado["ingredients_at_risk_eod"], poblado["ingredients_critical_eod"]) == (1, 0)  # K6: chorizo en 30
    assert float(poblado["telemetry_coverage_pct"]) == 66.67 and poblado["events_deduplicated"] == 1  # 2 de 3 salidas vistas
    assert poblado["capture_health"] == "ok" and poblado["revision"] == 1
    assert len([key for key in daily() if key[0] == YESTERDAY]) == 14  # los 14 restaurantes, también los sin actividad
    # Log de ejecución (≥ 5 campos de metadata)
    with engine.connect() as connection:
        log = connection.execute(text("SELECT * FROM reporting.pipeline_runs")).mappings().one()
    assert log["status"] == "completed" and log["trigger"] == "manual" and log["started_at"] <= log["finished_at"]
    assert log["rows_extracted"] == 5 and log["rows_deduplicated"] == 1 and log["rows_inserted"] == 42 and log["errors"] == []
    assert scalar("SELECT last_event_id FROM reporting.pipeline_watermarks") == log["watermark_to"] > 0


# ----------------------------------------------------------------- idempotencia
def test_running_twice_gives_identical_results_without_duplicates_or_new_revisions():
    seed()
    run()
    first = daily()
    second_result = run()
    assert daily() == first  # byte a byte: mismos valores, mismo computed_at, misma revisión (la segunda corrida fue un no-op)
    assert second_result["rows_inserted"] == 0 and second_result["rows_updated"] == 0 and second_result["unchanged"] == len(first)
    assert scalar("SELECT COUNT(*) FROM reporting.restaurant_inventory_daily_revisions") == 0
    assert scalar("SELECT COUNT(*) FROM reporting.pipeline_runs WHERE status = 'completed'") == 2  # dos corridas, una sola verdad


def test_a_range_run_matches_the_incremental_run_for_the_same_day():
    seed()
    run()
    before = daily()
    result = run(date_from=YESTERDAY, date_to=YESTERDAY)
    assert result["rows_updated"] == 0 and daily() == before  # mismo código, mismo resultado por cualquiera de los dos caminos
    assert scalar("SELECT trigger FROM reporting.pipeline_runs ORDER BY started_at DESC LIMIT 1") == "manual"


def test_a_range_run_does_not_move_the_checkpoint():
    seed()
    run(date_from=YESTERDAY, date_to=YESTERDAY)
    assert scalar("SELECT last_event_id FROM reporting.pipeline_watermarks") == 0  # recalcular el pasado no salta eventos nuevos
    assert daily()[(YESTERDAY, POBLADO)]["outbound_orders"] == 2


# ----------------------------------------------------------------- eventos tardíos
def test_a_late_event_corrects_the_published_day_and_keeps_the_previous_value():
    seed()
    run()
    add_late_order()
    result = run()
    row = daily()[(YESTERDAY, POBLADO)]
    assert row["outbound_orders"] == 3 and float(row["units_issued"]) == 17.0 and row["revision"] == 2  # corregido, no inflado
    assert result["rows_updated"] >= 1
    with engine.connect() as connection:
        old = connection.execute(text("SELECT outbound_orders, revision FROM reporting.restaurant_inventory_daily_revisions WHERE restaurant = :r"), {"r": POBLADO}).one()
    assert tuple(old) == (2, 1)  # el valor anterior quedó en el histórico


# ----------------------------------------------------------------- resiliencia
def test_a_failure_in_the_load_rolls_everything_back_and_the_next_run_recovers(monkeypatch):
    seed()
    monkeypatch.setattr(pipeline, "load_restaurant_inventory_daily", pipeline.load_restaurant_inventory_daily.with_options(retries=1, retry_delay_seconds=0))
    real = db._advance_watermark
    monkeypatch.setattr(db, "_advance_watermark", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("conexión perdida")))
    with pytest.raises(pipeline.PipelineStageError):
        run()
    assert daily() == {}  # el upsert ya se había ejecutado: la transacción lo revirtió entero (ningún cubo a medias)
    assert scalar("SELECT last_event_id FROM reporting.pipeline_watermarks") == 0  # el checkpoint no avanzó
    with engine.connect() as connection:
        failed = connection.execute(text("SELECT status, errors FROM reporting.pipeline_runs")).one()
    assert failed.status == "failed" and failed.errors[0]["stage"] == "load_restaurant_inventory_daily" and failed.errors[0]["retries_configured"] == 1
    monkeypatch.setattr(db, "_advance_watermark", real)
    assert run()["status"] == "completed"  # la corrida siguiente equivale a una limpia
    assert daily()[(YESTERDAY, POBLADO)]["outbound_orders"] == 2 and scalar("SELECT COUNT(*) FROM reporting.restaurant_inventory_daily WHERE restaurant = 'Brasaland El Poblado'") == 3


def test_a_transient_failure_is_absorbed_by_the_retries(monkeypatch):
    seed()
    monkeypatch.setattr(pipeline, "load_restaurant_inventory_daily", pipeline.load_restaurant_inventory_daily.with_options(retries=2, retry_delay_seconds=0))
    real, attempts = db._advance_watermark, []

    def flaky(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("corte de red momentáneo")
        return real(*args, **kwargs)

    monkeypatch.setattr(db, "_advance_watermark", flaky)
    assert run()["status"] == "completed" and len(attempts) == 2  # falló una vez y el reintento lo resolvió sin intervención
    assert scalar("SELECT COUNT(*) FROM reporting.restaurant_inventory_daily WHERE restaurant = 'Brasaland El Poblado'") == 3  # sin duplicados


def test_an_optional_task_failure_does_not_interrupt_extract_transform_load(monkeypatch):
    seed()

    @task(name="export_eval_snapshot")
    def broken_export(rows, run_id, summary, warnings):
        raise OSError("disco lleno")

    monkeypatch.setattr(pipeline, "export_eval_snapshot", broken_export)
    result = run()
    assert result["status"] == "completed" and result["optional_failures"] == ["export_inventory_validation_snapshot"]
    assert daily()[(YESTERDAY, POBLADO)]["outbound_orders"] == 2  # el ETL principal terminó
    with engine.connect() as connection:
        errors = connection.execute(text("SELECT errors FROM reporting.pipeline_runs")).scalar_one()
    assert errors[0]["stage"] == "export_inventory_validation_snapshot" and errors[0]["severity"] == "warning" and "disco lleno" in errors[0]["message"]


def test_invalid_kpis_block_the_load(monkeypatch):
    seed()
    real = pipeline.kpi.assemble_daily_kpis
    monkeypatch.setattr(pipeline.kpi, "assemble_daily_kpis", lambda *args, **kwargs: real(*args, **kwargs).assign(outbound_orders=-1))
    with pytest.raises(pipeline.PipelineStageError):
        run()
    assert daily() == {}  # una carga mala es peor que ninguna carga
    assert scalar("SELECT errors->0->>'stage' FROM reporting.pipeline_runs") == "validate_kpis"


# ----------------------------------------------------------------- caché
def test_the_expensive_transform_is_not_repeated_within_the_hour(monkeypatch):
    seed()
    calls = []
    real = pipeline.kpi.assemble_daily_kpis
    monkeypatch.setattr(pipeline.kpi, "assemble_daily_kpis", lambda *args, **kwargs: calls.append(1) or real(*args, **kwargs))
    run()
    run()
    assert len(calls) == 1  # la segunda corrida reutilizó el resultado (misma clave de caché: mismos datos)
    add_late_order()
    run()
    assert len(calls) == 2  # llegaron datos nuevos → otra clave → se recalcula (la caché nunca sirve números viejos)


# ----------------------------------------------------------------- candado de concurrencia
def _insert_running(heartbeat_age: timedelta) -> str:
    db.ensure_reporting_schema(engine)
    run_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO reporting.pipeline_runs (run_id, pipeline_name, trigger, started_at, status, code_version, heartbeat_at) "
                "VALUES (:id, :name, 'cron', now(), 'running', 'x', now() - make_interval(secs => :age))"
            ),
            {"id": run_id, "name": settings.PIPELINE_NAME, "age": heartbeat_age.total_seconds()},
        )
    return run_id


def test_a_second_run_while_one_is_active_is_skipped_and_recorded():
    seed()
    active = _insert_running(timedelta(seconds=5))
    result = run()
    assert result["status"] == "skipped_locked" and daily() == {}
    assert scalar(f"SELECT status FROM reporting.pipeline_runs WHERE run_id = '{result['run_id']}'") == "skipped_locked"
    assert scalar(f"SELECT status FROM reporting.pipeline_runs WHERE run_id = '{active}'") == "running"  # la activa no se toca


def test_a_run_that_died_without_closing_is_marked_crashed_and_does_not_block_forever():
    seed()
    dead = _insert_running(settings.HEARTBEAT_TIMEOUT + timedelta(minutes=1))
    assert run()["status"] == "completed"
    assert scalar(f"SELECT status FROM reporting.pipeline_runs WHERE run_id = '{dead}'") == "crashed"


# ----------------------------------------------------------------- endpoints sobre datos reales
@pytest.fixture
def headers(auth_headers):
    return auth_headers()


def test_kpis_endpoint_serves_the_rows_of_the_destination_table(client, headers):
    seed()
    run()
    response = client.get("/reporting/inventory-performance/kpis", params={"from": str(YESTERDAY), "to": str(YESTERDAY), "country": "Colombia"}, headers=headers)
    assert response.status_code == 200
    items = {item["restaurant"]: item for item in response.json()["items"]}
    assert len(items) == 10 and set(item["country"] for item in items.values()) == {"Colombia"}  # el filtro por país funciona
    assert items[POBLADO]["outbound_orders"] == 2 and items[POBLADO]["spoilage_rate_pct"] == 66.67 and items[POBLADO]["capture_health"] == "ok"
    week = client.get("/reporting/inventory-performance/kpis", params={"from": str(YESTERDAY), "to": str(YESTERDAY), "restaurant": POBLADO, "granularity": "week"}, headers=headers).json()["items"]
    assert len(week) == 1 and week[0]["outbound_orders"] == 2 and week[0]["spoilage_rate_pct"] == 66.67


def test_status_endpoint_reports_the_last_run(client, headers):
    before = client.get("/reporting/inventory-performance/status", headers=headers).json()
    assert before["last_run"] is None and before["is_stale"] is True  # antes de cualquier corrida
    seed()
    run()
    status = client.get("/reporting/inventory-performance/status", headers=headers).json()
    assert status["last_run"]["status"] == "completed" and status["last_run"]["rows_inserted"] == 42
    assert status["is_running"] is False and status["is_stale"] is False and status["watermark_lag"] == 0
    assert status["last_run"]["started_at"] and status["last_run"]["finished_at"] and status["last_success_at"]


def test_manual_trigger_runs_the_same_flow_and_blocks_a_concurrent_one(client, headers, monkeypatch):
    seed()
    launched = []

    def run_inline(run_id, triggered_by, window):  # en producción es un hilo; aquí síncrono para poder comprobar el resultado
        launched.append((run_id, triggered_by))
        pipeline.inventory_performance_daily_flow(trigger="manual", triggered_by=triggered_by, run_id=run_id)

    monkeypatch.setattr(pipeline_api, "_launch_flow", run_inline)
    response = client.post("/reporting/inventory-performance/runs", headers=headers)
    assert response.status_code == 202 and response.json()["status"] == "queued"
    run_id = response.json()["run_id"]
    assert launched == [(run_id, 1)]  # el id de la corrida devuelto es el de la corrida real; `triggered_by` = el usuario autenticado
    assert scalar(f"SELECT status FROM reporting.pipeline_runs WHERE run_id = '{run_id}'") == "completed"
    assert scalar(f"SELECT triggered_by FROM reporting.pipeline_runs WHERE run_id = '{run_id}'") == 1
    assert daily()[(YESTERDAY, POBLADO)]["outbound_orders"] == 2

    active = _insert_running(timedelta(seconds=5))
    conflict = client.post("/reporting/inventory-performance/runs", headers=headers)
    assert conflict.status_code == 409 and conflict.json()["run_id"] == active
