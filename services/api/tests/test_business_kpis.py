"""Transformaciones puras del pipeline de desempeño de negocio (`data/process/business_kpis.py`).

No usan base de datos ni Prefect: DataFrames de entrada → DataFrames de salida. Cada test fija UNA regla
de `data/pipelines/PIPELINE_DESIGN.md` (día local, deduplicación por clave de negocio, cuarentena,
recalcular-no-incrementar, K1–K6, capture_health, kpi_hash, validación).
"""
from __future__ import annotations

import ast
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest

from data.process import business_kpis as kpi

UTC = timezone.utc
POBLADO = "Brasaland El Poblado"  # America/Bogota (UTC-5, sin horario de verano)
BRICKELL = "Brasaland Brickell"  # America/New_York (UTC-4 en octubre)
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)

DIM = pd.DataFrame(
    [
        {"restaurant": POBLADO, "country": "Colombia", "city": "Medellín", "timezone": "America/Bogota"},
        {"restaurant": BRICKELL, "country": "Estados Unidos", "city": "Miami", "timezone": "America/New_York"},
        {"restaurant": kpi.UNATTRIBUTED, "country": "N/A", "city": "N/A", "timezone": "UTC"},
    ]
)


def raw_events(*rows: tuple) -> pd.DataFrame:
    """Filas crudas como las lee la extracción: (id, event_type, service, timestamp_utc, tags)."""
    return pd.DataFrame(
        [
            {"id": i, "event_id": str(uuid4()), "event_type": t, "service": s, "timestamp": ts, "tags": tags}
            for i, t, s, ts, tags in rows
        ]
    )


def prepared(raw: pd.DataFrame) -> pd.DataFrame:
    return kpi.assign_buckets(kpi.flatten_events(raw), DIM)


# ----------------------------------------------------------------- día local
def test_report_date_is_the_local_day_of_each_restaurant():
    raw = raw_events(
        (1, kpi.OUTBOUND_ORDER_CREATED, "frontend", datetime(2026, 10, 6, 3, 30, tzinfo=UTC), {"restaurant": POBLADO}),  # 22:30 del 5 en Bogotá
        (2, kpi.OUTBOUND_ORDER_CREATED, "frontend", datetime(2026, 10, 6, 5, 30, tzinfo=UTC), {"restaurant": POBLADO}),  # 00:30 del 6 en Bogotá
        (3, kpi.OUTBOUND_ORDER_CREATED, "frontend", datetime(2026, 10, 6, 3, 30, tzinfo=UTC), {"restaurant": BRICKELL}),  # 23:30 del 5 en Miami
        (4, kpi.OUTBOUND_ORDER_CREATED, "frontend", datetime(2026, 10, 6, 4, 30, tzinfo=UTC), {"restaurant": BRICKELL}),  # 00:30 del 6 en Miami
    )
    assert list(prepared(raw)["report_date"]) == [date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 5), date(2026, 10, 6)]


def test_unknown_or_missing_restaurant_goes_to_the_unattributed_bucket():
    raw = raw_events(
        (1, kpi.OUTBOUND_ORDER_CREATED, "frontend", NOW, {"restaurant": "unknown"}),
        (2, kpi.INVENTORY_VALIDATION_FAILED, "frontend", NOW, {}),
        (3, kpi.OUTBOUND_ORDER_CREATED, "frontend", NOW, {"restaurant": POBLADO}),
    )
    result = prepared(raw)
    assert list(result["restaurant"]) == [kpi.UNATTRIBUTED, kpi.UNATTRIBUTED, POBLADO]
    assert list(result["unattributed"]) == [True, True, False]


# ----------------------------------------------------------------- cuarentena
def test_quarantine_future_and_ancient_timestamps():
    raw = raw_events(
        (1, kpi.OUTBOUND_ORDER_CREATED, "frontend", datetime(2026, 10, 7, 11, 59, tzinfo=UTC), {}),  # ok
        (2, kpi.OUTBOUND_ORDER_CREATED, "frontend", datetime(2026, 10, 7, 12, 4, tzinfo=UTC), {}),  # +4 min: tolerado
        (3, kpi.OUTBOUND_ORDER_CREATED, "frontend", datetime(2026, 10, 7, 12, 6, tzinfo=UTC), {}),  # +6 min: cuarentena
        (4, kpi.OUTBOUND_ORDER_CREATED, "frontend", datetime(2026, 9, 1, 0, 0, tzinfo=UTC), {}),  # > 30 días: cuarentena
    )
    accepted, quarantined = kpi.quarantine_events(kpi.flatten_events(raw), NOW)
    assert list(accepted["id"]) == [1, 2] and quarantined == 2
    # En un rango explícito (backfill) la antigüedad no cuenta; el futuro imposible sí.
    accepted, quarantined = kpi.quarantine_events(kpi.flatten_events(raw), NOW, max_age=None)
    assert list(accepted["id"]) == [1, 2, 4] and quarantined == 1


# ----------------------------------------------------------------- deduplicación
def test_dedupe_by_business_key_prefers_backend_over_frontend():
    raw = raw_events(
        (1, kpi.OUTBOUND_ORDER_CREATED, "frontend", NOW, {"exitId": 9, "quantity": 2}),
        (2, kpi.OUTBOUND_ORDER_CREATED, "backend", NOW, {"exitId": 9, "quantity": 2}),  # misma orden, otro emisor
        (3, kpi.OUTBOUND_ORDER_CREATED, "frontend", NOW, {"exitId": 10, "quantity": 1}),
        (4, kpi.STOCK_THRESHOLD_TRIGGERED, "frontend", NOW, {"triggeringExitId": 9, "level": "low"}),
        (5, kpi.STOCK_THRESHOLD_TRIGGERED, "frontend", NOW, {"triggeringExitId": 9, "level": "low"}),  # duplicado
        (6, kpi.STOCK_THRESHOLD_TRIGGERED, "frontend", NOW, {"triggeringExitId": 9, "level": "critical"}),  # otro nivel: distinto
        (7, kpi.OUTBOUND_ORDER_CREATED, "frontend", NOW, {"quantity": 1}),  # sin exitId: se identifica por event_id
        (8, kpi.OUTBOUND_ORDER_CREATED, "frontend", NOW, {"quantity": 1}),  # sin exitId: NO se funde con el 7
    )
    kept, dropped = kpi.dedupe_events(kpi.flatten_events(raw))
    assert list(kept["id"]) == [2, 3, 4, 6, 7, 8]
    assert list(dropped["id"]) == [1, 5]


# ----------------------------------------------------------------- planificación de cubos
def test_plan_buckets_includes_late_events_and_the_lookback_window():
    late = prepared(raw_events((1, kpi.OUTBOUND_ORDER_CREATED, "frontend", datetime(2026, 9, 20, 15, 0, tzinfo=UTC), {"restaurant": POBLADO})))
    buckets = kpi.plan_buckets(late, DIM, NOW, lookback_days=3)
    # evento tardío del 20 de septiembre reabre ese día + 3 días × 2 restaurantes reales (UNATTRIBUTED no se programa)
    assert (date(2026, 9, 20), POBLADO) in set(map(tuple, buckets.to_numpy()))
    assert len(buckets) == 1 + 3 * 2
    assert kpi.UNATTRIBUTED not in set(buckets["restaurant"])
    assert date(2026, 10, 7) in set(buckets["report_date"]) and date(2026, 10, 5) in set(buckets["report_date"])


def test_plan_buckets_with_explicit_window_covers_every_day_and_restaurant():
    events = prepared(raw_events((1, kpi.OUTBOUND_ORDER_CREATED, "frontend", datetime(2026, 10, 1, 12, 0, tzinfo=UTC), {"restaurant": "unknown"})))
    buckets = kpi.plan_buckets(events, DIM, NOW, lookback_days=3, window=(date(2026, 10, 1), date(2026, 10, 3)))
    assert len(buckets) == 3 * 2 + 1  # 3 días × 2 restaurantes + el cubo UNATTRIBUTED con eventos
    assert buckets["report_date"].min() == date(2026, 10, 1) and buckets["report_date"].max() == date(2026, 10, 3)


# ----------------------------------------------------------------- K1–K6
def build_scenario():
    """Día 2026-10-05 en El Poblado con órdenes, merma, alertas y un rechazo; Brickell sin actividad."""
    day = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)  # 10:00 hora de Bogotá
    raw = raw_events(
        (1, kpi.OUTBOUND_ORDER_CREATED, "frontend", day, {"restaurant": POBLADO, "exitId": 1, "quantity": 2}),
        (2, kpi.OUTBOUND_ORDER_CREATED, "frontend", day, {"restaurant": POBLADO, "exitId": 2, "quantity": 3}),
        (3, kpi.OUTBOUND_ORDER_CREATED, "frontend", day, {"restaurant": POBLADO, "exitId": 3, "quantity": 5}),
        (4, kpi.STOCK_THRESHOLD_TRIGGERED, "frontend", day, {"restaurant": POBLADO, "level": "low", "triggeringExitId": 1}),
        (5, kpi.STOCK_THRESHOLD_TRIGGERED, "frontend", day, {"restaurant": POBLADO, "level": "critical", "triggeringExitId": 2}),
        (6, kpi.STOCK_THRESHOLD_TRIGGERED, "frontend", day, {"restaurant": POBLADO, "level": "critical", "triggeringExitId": 3}),
        (7, kpi.INVENTORY_VALIDATION_FAILED, "frontend", day, {"restaurant": POBLADO}),
    )
    events, dropped = kpi.dedupe_events(prepared(raw))
    exits = pd.DataFrame(
        [
            {"exit_id": 1, "reason": "Uso en cocina", "created_at": day, "restaurant": POBLADO},
            {"exit_id": 2, "reason": "Merma por vencimiento", "created_at": day, "restaurant": POBLADO},
            {"exit_id": 3, "reason": None, "created_at": day, "restaurant": POBLADO},
            {"exit_id": 4, "reason": "Uso en cocina", "created_at": day, "restaurant": POBLADO},  # la telemetría NO la vio
            {"exit_id": 5, "reason": "Uso en cocina", "created_at": datetime(2026, 10, 6, 15, 0, tzinfo=UTC), "restaurant": BRICKELL},
        ]
    )
    before = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    movements = pd.DataFrame(
        [  # stock al cierre del 5: ing.1 = 30 (en riesgo), ing.2 = 100 (sano), ing.3 = 5 (crítico), ing.4 = aún no existía
            {"ingredient_id": 1, "restaurant": POBLADO, "ts": before, "delta": 40.0},
            {"ingredient_id": 1, "restaurant": POBLADO, "ts": day, "delta": -10.0},
            {"ingredient_id": 2, "restaurant": POBLADO, "ts": before, "delta": 100.0},
            {"ingredient_id": 3, "restaurant": POBLADO, "ts": before, "delta": 20.0},
            {"ingredient_id": 3, "restaurant": POBLADO, "ts": day, "delta": -15.0},
            {"ingredient_id": 4, "restaurant": POBLADO, "ts": datetime(2026, 10, 6, 5, 30, tzinfo=UTC), "delta": 3.0},  # 00:30 del 6 local
        ]
    )
    buckets = pd.DataFrame(
        {"report_date": [date(2026, 10, 5), date(2026, 10, 5), date(2026, 10, 6)], "restaurant": [POBLADO, BRICKELL, BRICKELL]}
    )
    dropped = pd.DataFrame({"report_date": [date(2026, 10, 5)] * 2, "restaurant": [POBLADO] * 2, "event_id": ["a", "b"]})
    return events, exits, movements, buckets, dropped


def test_kpis_k1_to_k6_and_quality_columns():
    events, exits, movements, buckets, dropped = build_scenario()
    rows = kpi.compute_daily_kpis(events, exits, movements, buckets, DIM, dropped, source_max_event_id=77)
    poblado = rows[(rows["restaurant"] == POBLADO)].iloc[0]
    assert poblado["outbound_orders"] == 3  # K1
    assert poblado["units_issued"] == 10.0  # K2
    assert poblado["spoilage_units"] == 3.0 and poblado["spoilage_rate_pct"] == 30.0  # K3: solo la salida 2 es «Merma…»
    assert (poblado["stock_alerts_low"], poblado["stock_alerts_critical"]) == (1, 2)  # K4
    assert poblado["validation_failures"] == 1 and poblado["validation_rejection_rate_pct"] == 25.0  # K5: 1 ÷ (3+1)
    assert (poblado["ingredients_at_risk_eod"], poblado["ingredients_critical_eod"]) == (2, 1)  # K6: ing.1 (30) e ing.3 (5)
    assert poblado["telemetry_coverage_pct"] == 75.0  # 3 de las 4 salidas reales llegaron por telemetría
    assert poblado["events_deduplicated"] == 2 and poblado["capture_health"] == kpi.CAPTURE_OK
    assert poblado["source_max_event_id"] == 77


def test_capture_health_separates_real_zero_from_a_capture_gap():
    events, exits, movements, buckets, dropped = build_scenario()
    rows = kpi.compute_daily_kpis(events, exits, movements, buckets, DIM, dropped, source_max_event_id=1).set_index(["report_date", "restaurant"])
    quiet = rows.loc[(date(2026, 10, 5), BRICKELL)]
    gap = rows.loc[(date(2026, 10, 6), BRICKELL)]
    assert quiet["capture_health"] == kpi.CAPTURE_REAL_ZERO  # 0 órdenes y 0 salidas reales: ausencia real
    assert pd.isna(quiet["spoilage_rate_pct"]) and pd.isna(quiet["telemetry_coverage_pct"])  # sin denominador → NULL, no 0
    assert gap["capture_health"] == kpi.CAPTURE_GAP  # hubo una salida real y ningún evento: silencio sospechoso
    assert gap["outbound_orders"] == 0 and gap["telemetry_coverage_pct"] == 0.0


def test_stock_at_close_uses_local_midnight_not_utc():
    events, exits, movements, buckets, dropped = build_scenario()
    rows = kpi.compute_daily_kpis(events, exits, movements, buckets, DIM, dropped, source_max_event_id=1)
    # El insumo 4 entra a las 00:30 locales del día 6: NO existe todavía al cierre del 5, pero sí al del 6.
    day6 = kpi.compute_daily_kpis(
        events, exits, movements, pd.DataFrame({"report_date": [date(2026, 10, 6)], "restaurant": [POBLADO]}), DIM, dropped, 1
    ).iloc[0]
    assert rows[rows["restaurant"] == POBLADO].iloc[0]["ingredients_at_risk_eod"] == 2
    # Al cierre del 6: ing.1 (30) e ing.3 (5) siguen en riesgo y ing.4 (3) ya existe → 3 en riesgo, 2 críticos; ing.2 (100) sano.
    assert (day6["ingredients_at_risk_eod"], day6["ingredients_critical_eod"]) == (3, 2)


def test_recompute_is_deterministic_and_the_hash_ignores_run_metadata():
    events, exits, movements, buckets, dropped = build_scenario()
    first = kpi.compute_daily_kpis(events, exits, movements, buckets, DIM, dropped, source_max_event_id=10)
    second = kpi.compute_daily_kpis(events, exits, movements, buckets, DIM, dropped, source_max_event_id=999)
    pd.testing.assert_series_equal(first["kpi_hash"], second["kpi_hash"])  # mismos datos → misma huella aunque cambie el tope de id
    changed = events.assign(quantity=events["quantity"] + 1)
    third = kpi.compute_daily_kpis(changed, exits, movements, buckets, DIM, dropped, source_max_event_id=10)
    poblado = lambda frame: frame[frame["restaurant"] == POBLADO].iloc[0]["kpi_hash"]  # noqa: E731
    assert poblado(first) != poblado(third)  # otro valor → otra huella
    brickell = lambda frame: frame[(frame["restaurant"] == BRICKELL)]["kpi_hash"].tolist()  # noqa: E731
    assert brickell(first) == brickell(third)  # los cubos que no cambiaron conservan su huella


def test_empty_inputs_still_produce_zero_rows_for_every_bucket():
    events = kpi.dedupe_events(kpi.assign_buckets(kpi.flatten_events(pd.DataFrame()), DIM))[0]
    exits = pd.DataFrame({"exit_id": [], "reason": [], "created_at": [], "restaurant": []})
    movements = pd.DataFrame({"ingredient_id": [], "restaurant": [], "ts": [], "delta": []})
    buckets = pd.DataFrame({"report_date": [date(2026, 10, 5)], "restaurant": [POBLADO]})
    rows = kpi.compute_daily_kpis(events, exits, movements, buckets, DIM, events, source_max_event_id=0)
    assert len(rows) == 1 and rows.loc[0, "outbound_orders"] == 0 and rows.loc[0, "capture_health"] == kpi.CAPTURE_REAL_ZERO


# ----------------------------------------------------------------- validación
def test_validation_blocks_impossible_values_and_only_warns_about_over_coverage():
    events, exits, movements, buckets, dropped = build_scenario()
    rows = kpi.compute_daily_kpis(events, exits, movements, buckets, DIM, dropped, source_max_event_id=1)
    assert kpi.validate_kpi_rows(rows) == []
    with pytest.raises(kpi.KpiValidationError, match="spoilage_rate_pct"):
        kpi.validate_kpi_rows(rows.assign(spoilage_rate_pct=130.0))
    with pytest.raises(kpi.KpiValidationError, match="negativos"):
        kpi.validate_kpi_rows(rows.assign(outbound_orders=-1))
    warnings = kpi.validate_kpi_rows(rows.assign(telemetry_coverage_pct=140.0))
    assert warnings and "cobertura" in warnings[0]  # aviso, no excepción


# ----------------------------------------------------------------- vista semanal
def test_weekly_aggregation_recomputes_rates_from_sums():
    daily = pd.DataFrame(
        [
            {"report_date": date(2026, 10, 5), "restaurant": POBLADO, "country": "Colombia", "outbound_orders": 1, "units_issued": 10.0, "spoilage_units": 10.0,
             "stock_alerts_low": 0, "stock_alerts_critical": 1, "validation_failures": 0, "events_deduplicated": 0, "ingredients_at_risk_eod": 3,
             "ingredients_critical_eod": 1, "telemetry_coverage_pct": 100.0, "capture_health": "ok", "revision": 1},
            {"report_date": date(2026, 10, 7), "restaurant": POBLADO, "country": "Colombia", "outbound_orders": 3, "units_issued": 90.0, "spoilage_units": 0.0,
             "stock_alerts_low": 1, "stock_alerts_critical": 0, "validation_failures": 1, "events_deduplicated": 2, "ingredients_at_risk_eod": 1,
             "ingredients_critical_eod": 0, "telemetry_coverage_pct": 100.0, "capture_health": "suspected_capture_gap", "revision": 2},
        ]
    )
    week = kpi.aggregate_weekly(daily).iloc[0]
    assert week["report_date"] == date(2026, 10, 5)  # lunes de esa semana
    assert week["outbound_orders"] == 4 and week["units_issued"] == 100.0
    assert week["spoilage_rate_pct"] == 10.0  # 10 ÷ 100, NO el promedio de 100 % y 0 %
    assert week["validation_rejection_rate_pct"] == 20.0  # 1 ÷ (4 + 1)
    assert (week["ingredients_at_risk_eod"], week["ingredients_critical_eod"]) == (1, 0)  # cierre del último día
    assert week["capture_health"] == "suspected_capture_gap" and week["revision"] == 2


# ----------------------------------------------------------------- pureza
def test_business_kpis_module_is_pure_no_io_imports():
    tree = ast.parse(Path(kpi.__file__).read_text())
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert imported.isdisjoint({"sqlalchemy", "sqlmodel", "prefect", "requests", "psycopg2", "fastapi"})
