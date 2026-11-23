"""Tests unitarios de las tasks de TRANSFORMACIÓN del pipeline «Desempeño de Inventario por Restaurante».

    python -m pytest tests/pipelines/test_pipeline.py

Aislamiento: cada test llama a la task con `.fn(...)` (la función de Python que hay dentro de la task de Prefect)
y le pasa DataFrames en memoria con la FORMA de las filas de `telemetry_events` (`id`, `event_id`, `event_type`,
`service`, `timestamp`, `tags`). No hay base de datos, ni red, ni servidor de Prefect (salvo el último test, que
ejecuta un subflow con el arnés local de pruebas de Prefect).

Vocabulario: los nombres de los tests siguen los KPI de `data/pipelines/PIPELINE_DESIGN.md` §2.3:
K1 `outbound_orders`, K2 `units_issued`, K3 `spoilage_rate_pct`, K4 `stock_alerts_low/critical`,
K5 `validation_rejection_rate_pct`, K6 `ingredients_at_risk_eod`.
"""
from __future__ import annotations

import ast
import math
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest

from data.pipelines import pipeline
from data.process import business_kpis as kpi

UTC = timezone.utc
POBLADO = "Brasaland El Poblado"  # America/Bogota (UTC-5)
BRICKELL = "Brasaland Brickell"  # America/New_York
OCT_5 = date(2026, 10, 5)
NOON_OCT_5 = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)  # 10:00 en Bogotá → día local 2026-10-05
FINGERPRINT = "test-fingerprint"  # la caché de Prefect no interviene al llamar a `.fn`

DIM = pd.DataFrame(
    [
        {"restaurant": POBLADO, "country": "Colombia", "city": "Medellín", "timezone": "America/Bogota"},
        {"restaurant": BRICKELL, "country": "Estados Unidos", "city": "Miami", "timezone": "America/New_York"},
        {"restaurant": kpi.UNATTRIBUTED, "country": "N/A", "city": "N/A", "timezone": "UTC"},
    ]
)
BUCKETS = pd.DataFrame({"report_date": [OCT_5], "restaurant": [POBLADO]})


# --------------------------------------------------------------------------- #
# Datos de prueba en memoria (forma de `telemetry_events`)
# --------------------------------------------------------------------------- #
def telemetry(*rows: tuple) -> pd.DataFrame:
    """Filas como las lee la extracción: (id, event_type, service, timestamp, tags)."""
    return pd.DataFrame(
        [{"id": i, "event_id": str(uuid4()), "event_type": t, "service": s, "timestamp": ts, "tags": tags} for i, t, s, ts, tags in rows]
    )


def prepared(raw: pd.DataFrame) -> pd.DataFrame:
    """Lo que entregaría la task `prepare_telemetry_events` (eventos aplanados, con día local, sin duplicados)."""
    snapshot = {"events": raw, "dim": DIM}
    return pipeline.prepare_telemetry_events.fn(snapshot, FINGERPRINT)["events"]


def order(i: int, exit_id: int, quantity, service: str = "frontend", restaurant: str = POBLADO) -> tuple:
    return (i, kpi.OUTBOUND_ORDER_CREATED, service, NOON_OCT_5, {"restaurant": restaurant, "exitId": exit_id, "quantity": quantity})


def only_row(frame: pd.DataFrame) -> pd.Series:
    assert len(frame) == 1
    return frame.iloc[0]


# --------------------------------------------------------------------------- #
# K1 `outbound_orders` y K2 `units_issued`
# --------------------------------------------------------------------------- #
def test_k1_outbound_orders_and_k2_units_issued_are_counted_once_per_exit_id():
    raw = telemetry(
        order(1, exit_id=1, quantity=2),
        order(2, exit_id=2, quantity=3),
        order(3, exit_id=2, quantity=3, service="backend"),  # la MISMA salida emitida por backend y frontend: cuenta una vez
        order(4, exit_id=3, quantity=5),
    )
    result = pipeline.compute_outbound_orders_and_units_issued.fn(prepared(raw), BUCKETS, FINGERPRINT)
    row = only_row(result)
    assert row["outbound_orders"] == 3  # calculado a mano: salidas 1, 2 y 3
    assert row["units_issued"] == 10.0  # 2 + 3 + 5


def test_k1_and_k2_are_zero_for_a_bucket_without_activity():
    result = pipeline.compute_outbound_orders_and_units_issued.fn(prepared(telemetry()), BUCKETS, FINGERPRINT)
    row = only_row(result)
    assert (row["outbound_orders"], row["units_issued"]) == (0, 0.0)  # «no hubo salidas» es un 0 real, no un hueco


def test_k1_buckets_orders_by_the_local_day_of_each_restaurant():
    late_night = datetime(2026, 10, 6, 2, 0, tzinfo=UTC)  # 21:00 del 5 en Bogotá: sigue siendo el día local 5
    raw = telemetry((1, kpi.OUTBOUND_ORDER_CREATED, "frontend", late_night, {"restaurant": POBLADO, "exitId": 1, "quantity": 4}))
    result = pipeline.compute_outbound_orders_and_units_issued.fn(prepared(raw), BUCKETS, FINGERPRINT)
    assert only_row(result)["outbound_orders"] == 1


# --------------------------------------------------------------------------- #
# K3 `spoilage_rate_pct` — la definición del documento de diseño, calculada a mano
# --------------------------------------------------------------------------- #
def test_k3_spoilage_rate_pct_matches_the_design_definition_for_a_known_input():
    """Definición (§2.3): Σ quantity de salidas cuya razón empieza por «Merma» ÷ units_issued × 100."""
    raw = telemetry(order(1, 1, 2), order(2, 2, 3), order(3, 3, 5))
    exits = pd.DataFrame(
        [
            {"exit_id": 1, "reason": "Uso en cocina"},
            {"exit_id": 2, "reason": "  merma por vencimiento "},  # espacios y minúsculas: sigue siendo merma
            {"exit_id": 3, "reason": None},
        ]
    )
    result = pipeline.compute_spoilage_rate_pct.fn(prepared(raw), exits, BUCKETS, FINGERPRINT)
    row = only_row(result)
    assert row["spoilage_units"] == 3.0  # solo la salida 2
    assert row["spoilage_rate_pct"] == 30.0  # 3 ÷ (2 + 3 + 5) × 100
    assert "reason" not in result.columns  # el texto de la razón nunca sale de la task: solo el indicador


def test_k3_rate_is_undefined_not_zero_when_nothing_was_issued():
    result = pipeline.compute_spoilage_rate_pct.fn(prepared(telemetry()), pd.DataFrame({"exit_id": [], "reason": []}), BUCKETS, FINGERPRINT)
    row = only_row(result)
    assert row["spoilage_units"] == 0.0
    assert math.isnan(row["spoilage_rate_pct"])  # 0 ÷ 0 no es «0 % de merma»: es «sin datos»


# --------------------------------------------------------------------------- #
# K4 `stock_alerts_low` / `stock_alerts_critical`
# --------------------------------------------------------------------------- #
def test_k4_stock_alerts_count_each_downward_crossing_once():
    def alert(i, level, exit_id, service="frontend"):
        return (i, kpi.STOCK_THRESHOLD_TRIGGERED, service, NOON_OCT_5, {"restaurant": POBLADO, "level": level, "triggeringExitId": exit_id})

    raw = telemetry(alert(1, "low", 1), alert(2, "critical", 2), alert(3, "critical", 3), alert(4, "critical", 3, service="backend"))
    row = only_row(pipeline.compute_stock_alerts.fn(prepared(raw), BUCKETS, FINGERPRINT))
    assert (row["stock_alerts_low"], row["stock_alerts_critical"]) == (1, 2)  # el cruce de la salida 3 llegó duplicado


# --------------------------------------------------------------------------- #
# K5 `validation_rejection_rate_pct`
# --------------------------------------------------------------------------- #
def test_k5_validation_rejection_rate_pct_is_failures_over_orders_plus_failures():
    failure = (4, kpi.INVENTORY_VALIDATION_FAILED, "frontend", NOON_OCT_5, {"restaurant": POBLADO})
    raw = telemetry(order(1, 1, 2), order(2, 2, 3), order(3, 3, 5), failure)
    row = only_row(pipeline.compute_validation_rejection_rate_pct.fn(prepared(raw), BUCKETS, FINGERPRINT))
    assert row["validation_failures"] == 1
    assert row["validation_rejection_rate_pct"] == 25.0  # 1 ÷ (3 + 1) × 100


# --------------------------------------------------------------------------- #
# K6 `ingredients_at_risk_eod`
# --------------------------------------------------------------------------- #
def test_k6_ingredients_at_risk_eod_uses_stock_at_the_local_close_of_the_day():
    before, during = datetime(2026, 10, 4, 12, 0, tzinfo=UTC), NOON_OCT_5
    movements = pd.DataFrame(
        [  # stock al cierre del día 5: ing.1 = 30 (en riesgo), ing.2 = 100 (sano), ing.3 = 5 (crítico)
            {"ingredient_id": 1, "restaurant": POBLADO, "ts": before, "delta": 40.0},
            {"ingredient_id": 1, "restaurant": POBLADO, "ts": during, "delta": -10.0},
            {"ingredient_id": 2, "restaurant": POBLADO, "ts": before, "delta": 100.0},
            {"ingredient_id": 3, "restaurant": POBLADO, "ts": before, "delta": 20.0},
            {"ingredient_id": 3, "restaurant": POBLADO, "ts": during, "delta": -15.0},
            # 00:30 del día 6 en Bogotá: es DESPUÉS del cierre del 5, no puede contar
            {"ingredient_id": 4, "restaurant": POBLADO, "ts": datetime(2026, 10, 6, 5, 30, tzinfo=UTC), "delta": 3.0},
        ]
    )
    row = only_row(pipeline.compute_ingredients_at_risk_eod.fn(BUCKETS, movements, DIM, FINGERPRINT))
    assert row["ingredients_at_risk_eod"] == 2  # ing.1 (30 ≤ 30) e ing.3 (5)
    assert row["ingredients_critical_eod"] == 1  # solo ing.3 (5 ≤ 10)


# --------------------------------------------------------------------------- #
# Comportamiento DEFENSIVO ante inputs inválidos o malformados
# --------------------------------------------------------------------------- #
def test_defensive_prepare_telemetry_events_survives_malformed_payloads():
    """Tags nulos, texto que no es JSON, listas, cantidades no numéricas: ninguna rompe la task ni se pierde en silencio."""
    raw = telemetry(
        (1, kpi.OUTBOUND_ORDER_CREATED, "frontend", NOON_OCT_5, None),  # tags nulo
        (2, kpi.OUTBOUND_ORDER_CREATED, "frontend", NOON_OCT_5, "esto no es json"),  # tipo incorrecto
        (3, kpi.OUTBOUND_ORDER_CREATED, "frontend", NOON_OCT_5, ["lista", "inesperada"]),  # tipo incorrecto
        (4, kpi.OUTBOUND_ORDER_CREATED, "frontend", NOON_OCT_5, {"restaurant": POBLADO, "exitId": 9, "quantity": "mucho"}),  # cantidad no numérica
    )
    kept = pipeline.prepare_telemetry_events.fn({"events": raw, "dim": DIM}, FINGERPRINT)["events"]
    assert len(kept) == 4  # nada desaparece
    # Sin restaurante identificable → cubo UNATTRIBUTED (visible y contado), nunca se le adjudica a otro local.
    assert (kept[kept["id"].isin([1, 2, 3])]["restaurant"] == kpi.UNATTRIBUTED).all()
    bad_quantity = kept[kept["id"] == 4].iloc[0]
    assert bad_quantity["restaurant"] == POBLADO and pd.isna(bad_quantity["quantity"])  # NaN explícito, no un 0 inventado
    # Y el KPI no suma esa cantidad inválida a las unidades emitidas.
    row = only_row(pipeline.compute_outbound_orders_and_units_issued.fn(kept, BUCKETS, FINGERPRINT))
    assert row["units_issued"] == 0.0


def test_defensive_prepare_telemetry_events_drops_events_from_the_future():
    future = datetime(2999, 1, 1, tzinfo=UTC)  # reloj del navegador desajustado
    raw = telemetry((1, kpi.OUTBOUND_ORDER_CREATED, "frontend", future, {"restaurant": POBLADO, "exitId": 1, "quantity": 1}))
    assert pipeline.prepare_telemetry_events.fn({"events": raw, "dim": DIM}, FINGERPRINT)["events"].empty


def test_defensive_validate_kpis_blocks_impossible_values_before_loading():
    """`validate_kpis` es la última barrera antes de la carga: un KPI imposible detiene el flow."""
    good = kpi.compute_daily_kpis(
        prepared(telemetry(order(1, 1, 2))), pd.DataFrame({"exit_id": [1], "reason": ["Uso"], "created_at": [NOON_OCT_5], "restaurant": [POBLADO]}),
        pd.DataFrame({"ingredient_id": [], "restaurant": [], "ts": [], "delta": []}), BUCKETS, DIM,
        pd.DataFrame({"report_date": [], "restaurant": [], "event_id": []}), source_max_event_id=1,
    )
    assert pipeline.validate_kpis.fn(good) == []  # datos sanos: sin avisos

    negative = good.assign(outbound_orders=-1)
    with pytest.raises(kpi.KpiValidationError):
        pipeline.validate_kpis.fn(negative)
    impossible_rate = good.assign(spoilage_rate_pct=140.0)
    with pytest.raises(kpi.KpiValidationError):
        pipeline.validate_kpis.fn(impossible_rate)


# --------------------------------------------------------------------------- #
# Las tasks se ensamblan en una fila por restaurante y día, con calidad y hash estable
# --------------------------------------------------------------------------- #
def test_assemble_daily_kpis_flags_a_capture_gap_and_is_deterministic():
    exits = pd.DataFrame(
        [
            {"exit_id": 1, "reason": "Uso", "created_at": NOON_OCT_5, "restaurant": POBLADO},
            {"exit_id": 2, "reason": "Uso", "created_at": NOON_OCT_5, "restaurant": POBLADO},  # salida real que la telemetría no vio
        ]
    )
    events = prepared(telemetry(order(1, 1, 4)))
    movements = pd.DataFrame({"ingredient_id": [], "restaurant": [], "ts": [], "delta": []})
    dropped = pd.DataFrame({"report_date": [], "restaurant": [], "event_id": []})

    def build():
        parts = [
            pipeline.compute_outbound_orders_and_units_issued.fn(events, BUCKETS, FINGERPRINT),
            pipeline.compute_spoilage_rate_pct.fn(events, exits, BUCKETS, FINGERPRINT),
            pipeline.compute_stock_alerts.fn(events, BUCKETS, FINGERPRINT),
            pipeline.compute_validation_rejection_rate_pct.fn(events, BUCKETS, FINGERPRINT),
            pipeline.compute_ingredients_at_risk_eod.fn(BUCKETS, movements, DIM, FINGERPRINT),
        ]
        return pipeline.assemble_daily_kpis.fn(BUCKETS, parts, exits, dropped, DIM, 7, FINGERPRINT)

    first, second = only_row(build()), only_row(build())
    assert first["outbound_orders"] == 1 and first["telemetry_coverage_pct"] == 50.0  # 1 de 2 salidas reales
    assert first["capture_health"] == kpi.CAPTURE_OK
    assert first["source_max_event_id"] == 7
    assert first["kpi_hash"] == second["kpi_hash"]  # mismos datos → mismo hash (base de la idempotencia)


def test_assemble_daily_kpis_accepts_naive_exit_timestamps_as_utc():
    """Regresión (DEV-53): en Supabase `ingredient_exits.created_at` es `timestamp WITHOUT time zone` y llegaba sin zona,
    lo que tumbaba `assemble_daily_kpis` con «Cannot convert tz-naive timestamps» en cualquier día con salidas reales."""
    aware = pd.DataFrame([{"exit_id": 1, "reason": "Uso", "created_at": NOON_OCT_5, "restaurant": POBLADO}])
    naive = aware.assign(created_at=pd.Timestamp(NOON_OCT_5).tz_convert("UTC").tz_localize(None))  # misma hora UTC, sin zona
    events = prepared(telemetry(order(1, 1, 4)))
    movements = pd.DataFrame({"ingredient_id": [], "restaurant": [], "ts": [], "delta": []})
    dropped = pd.DataFrame({"report_date": [], "restaurant": [], "event_id": []})

    def build(exits):
        parts = [
            pipeline.compute_outbound_orders_and_units_issued.fn(events, BUCKETS, FINGERPRINT),
            pipeline.compute_spoilage_rate_pct.fn(events, exits, BUCKETS, FINGERPRINT),
            pipeline.compute_stock_alerts.fn(events, BUCKETS, FINGERPRINT),
            pipeline.compute_validation_rejection_rate_pct.fn(events, BUCKETS, FINGERPRINT),
            pipeline.compute_ingredients_at_risk_eod.fn(BUCKETS, movements, DIM, FINGERPRINT),
        ]
        return only_row(pipeline.assemble_daily_kpis.fn(BUCKETS, parts, exits, dropped, DIM, 7, FINGERPRINT))

    assert build(naive).to_dict() == build(aware).to_dict()  # sin zona = UTC: mismo resultado y mismo hash


def test_as_utc_treats_naive_as_utc_and_converts_aware():
    naive = pd.Series(pd.to_datetime(["2026-10-07 17:40:00"]))
    aware = pd.Series(pd.to_datetime(["2026-10-07 19:40:00+02:00"]))
    assert str(kpi.as_utc(naive).iloc[0]) == str(kpi.as_utc(aware).iloc[0]) == "2026-10-07 17:40:00+00:00"


# --------------------------------------------------------------------------- #
# Estructura de subflows (Fase 1 del ticket)
# --------------------------------------------------------------------------- #
def _called_names(function_name: str) -> set[str]:
    tree = ast.parse(Path(pipeline.__file__).read_text(encoding="utf-8"))
    function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == function_name)
    return {node.func.id for node in ast.walk(function) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}


def test_main_flow_coordinates_three_subflows_and_holds_no_stage_logic():
    calls = _called_names("inventory_performance_daily_flow")
    # Invoca los subflows (por `_run_subflow`) y el subflow opcional con `return_state=True`…
    flow_names = {"extract_inventory_telemetry_flow", "compute_inventory_kpis_flow", "load_restaurant_inventory_daily_flow"}
    source = Path(pipeline.__file__).read_text(encoding="utf-8")
    assert all(name in source.split("def inventory_performance_daily_flow")[1].split("def inventory_performance_backfill")[0] for name in flow_names)
    assert "export_inventory_validation_snapshot_flow" in calls
    # …y NO llama directamente a ninguna task de extracción, transformación o carga.
    stage_tasks = {
        "read_checkpoint", "extract_telemetry_events", "extract_domain_snapshot", "prepare_telemetry_events", "assemble_daily_kpis",
        "validate_kpis", "load_restaurant_inventory_daily", "compute_stock_alerts", "compute_spoilage_rate_pct",
    }
    assert calls.isdisjoint(stage_tasks)


@pytest.mark.parametrize(
    "subflow",
    [
        pipeline.extract_inventory_telemetry_flow,
        pipeline.compute_inventory_kpis_flow,
        pipeline.load_restaurant_inventory_daily_flow,
        pipeline.export_inventory_validation_snapshot_flow,
    ],
)
def test_every_subflow_is_a_prefect_flow_with_explicit_typed_inputs_and_outputs(subflow):
    import inspect

    signature = inspect.signature(subflow.fn)
    assert "run_id" in signature.parameters
    assert all(parameter.annotation is not inspect.Parameter.empty for parameter in signature.parameters.values())  # inputs tipados
    assert signature.return_annotation is not inspect.Signature.empty  # output declarado


def test_compute_inventory_kpis_subflow_runs_on_its_own_with_in_memory_data(monkeypatch):
    """El subflow de transformación se ejecuta de forma independiente: solo necesita su `snapshot`, no una base de datos."""
    from prefect.testing.utilities import prefect_test_harness

    monkeypatch.setattr(pipeline.db, "heartbeat", lambda *args, **kwargs: None)  # el latido sí toca la BD: aquí no existe
    events = telemetry(order(1, 1, 2), order(2, 2, 3))
    snapshot = {
        "events": events, "dim": DIM, "buckets": BUCKETS, "max_event_id": 2, "fingerprint": f"independent-{uuid4()}",
        "exits": pd.DataFrame(
            [
                {"exit_id": 1, "reason": "Uso en cocina", "created_at": NOON_OCT_5, "restaurant": POBLADO},
                {"exit_id": 2, "reason": "Merma por vencimiento", "created_at": NOON_OCT_5, "restaurant": POBLADO},
            ]
        ),
        "movements": pd.DataFrame({"ingredient_id": [], "restaurant": [], "ts": [], "delta": []}),
    }
    with prefect_test_harness():
        output = pipeline.compute_inventory_kpis_flow(run_id="unit-test", snapshot=snapshot)
    row = only_row(output["rows"])
    assert (row["outbound_orders"], row["units_issued"], row["spoilage_rate_pct"]) == (2, 5.0, 60.0)  # 3 de 5 unidades fueron merma
    assert output["buckets_recomputed"] == 1 and output["warnings"] == []
