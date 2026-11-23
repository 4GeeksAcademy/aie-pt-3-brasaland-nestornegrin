"""Transformaciones PURAS del pipeline «Desempeño de Inventario por Restaurante».

Aquí vive todo el cálculo de negocio (KPIs K1–K6 de `data/pipelines/PIPELINE_DESIGN.md` §2.3) sin tocar
la base de datos, Prefect ni la red: cada función recibe DataFrames y devuelve DataFrames. Por eso se
puede probar sin infraestructura y reutilizar desde cualquier flow (diseño §4, etapa «Transformación»).

Orden lógico de la etapa de transformación:

    flatten_events → quarantine_events → assign_buckets → dedupe_events
        → plan_buckets (qué cubos recalcular) → compute_daily_kpis → validate_kpi_rows

Reglas que se cumplen aquí (todas del diseño):
- **Recalcular, no incrementar** (§5.1.1): `compute_daily_kpis` recibe TODOS los eventos de cada cubo
  afectado y calcula el valor completo; nunca suma deltas a un valor ya publicado.
- **Día local** (§2.2): `report_date` es el día en la zona horaria del restaurante (`dim_restaurant`).
- **Deduplicación en dos capas** (§5.1.4): `eventId` ya lo garantiza el UNIQUE de la tabla; aquí se
  deduplica por clave de negocio (`exitId`; `triggeringExitId` + `level`) con prioridad backend > frontend.
- **Cuarentena** (§3.4): timestamps imposibles no entran en ningún KPI; restaurantes desconocidos van
  al cubo `UNATTRIBUTED`.
- **kpi_hash** (§5.1.2): huella de los valores calculados; permite que una segunda corrida sobre los
  mismos datos sea un no-op en la carga.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Constantes del dominio (nombres exactos de los eventos obligatorios del plan de telemetría)
# --------------------------------------------------------------------------- #
OUTBOUND_ORDER_CREATED = "outbound_order_created"
STOCK_THRESHOLD_TRIGGERED = "stock_threshold_triggered"
INVENTORY_VALIDATION_FAILED = "inventory_validation_failed"
KPI_EVENT_TYPES: tuple[str, ...] = (OUTBOUND_ORDER_CREATED, STOCK_THRESHOLD_TRIGGERED, INVENTORY_VALIDATION_FAILED)

UNATTRIBUTED = "UNATTRIBUTED"
DEFAULT_LOW_THRESHOLD = 30.0  # stock <= 30 → nivel «low»   (mismo umbral que el frontend)
DEFAULT_CRITICAL_THRESHOLD = 10.0  # stock <= 10 → nivel «critical»
FUTURE_TOLERANCE = timedelta(minutes=5)  # reloj del navegador adelantado más de esto → cuarentena
MAX_EVENT_AGE = timedelta(days=30)  # reloj atrasado más de esto → cuarentena (solo en corridas incrementales)
SPOILAGE_PREFIX = "merma"  # K3: `ingredient_exits.reason` que empieza por «Merma» (sin distinguir mayúsculas)

CAPTURE_OK = "ok"
CAPTURE_REAL_ZERO = "real_zero"
CAPTURE_GAP = "suspected_capture_gap"

BUCKET = ["report_date", "restaurant"]
TAG_FIELDS = ("restaurant", "exitId", "quantity", "level", "triggeringExitId")
SOURCE_PRIORITY = {"backend": 0, "frontend": 1, "job": 2}  # si dos lados emiten la misma orden, gana el backend

# Columnas de valores que alimentan `kpi_hash` (todo menos metadatos de la corrida).
KPI_VALUE_COLUMNS = [
    "outbound_orders",
    "units_issued",
    "spoilage_units",
    "spoilage_rate_pct",
    "stock_alerts_low",
    "stock_alerts_critical",
    "validation_failures",
    "validation_rejection_rate_pct",
    "ingredients_at_risk_eod",
    "ingredients_critical_eod",
    "telemetry_coverage_pct",
    "events_deduplicated",
    "capture_health",
]


class KpiValidationError(ValueError):
    """Los KPIs calculados violan una regla de calidad: la carga NO debe ejecutarse."""


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except ValueError:  # texto que no es JSON: se trata como «sin tags» (acabará en UNATTRIBUTED), no tumba la corrida
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def local_date(timestamps: pd.Series, zones: pd.Series) -> pd.Series:
    """Día calendario LOCAL de cada instante UTC, según la zona IANA de su fila."""
    if timestamps.empty:
        return pd.Series([], index=timestamps.index, dtype=object)
    parts = [stamps.dt.tz_convert(zone).dt.date for zone, stamps in timestamps.groupby(zones)]
    return pd.concat(parts).reindex(timestamps.index)


def _local_midnight_utc(days: pd.Series, zones: pd.Series) -> pd.Series:
    """Medianoche LOCAL (inicio de `days`) expresada en UTC."""
    naive = pd.to_datetime(days)
    parts = [
        stamps.dt.tz_localize(zone, nonexistent="shift_forward", ambiguous="NaT").dt.tz_convert("UTC")
        for zone, stamps in naive.groupby(zones)
    ]
    return pd.concat(parts).reindex(days.index)


def _zone_of(restaurants: pd.Series, dim: pd.DataFrame) -> pd.Series:
    return restaurants.map(dim.set_index("restaurant")["timezone"]).fillna("UTC")


def _native(value: Any) -> Any:
    """NaN/NA → None y tipos de numpy → tipos nativos (JSON/SQL-friendly)."""
    if value is None or (not isinstance(value, (str, bytes)) and pd.isna(value)):
        return None
    return value.item() if isinstance(value, np.generic) else value


# --------------------------------------------------------------------------- #
# 1 · Refinar eventos crudos
# --------------------------------------------------------------------------- #
def flatten_events(raw: pd.DataFrame) -> pd.DataFrame:
    """`tags` (JSON) → columnas planas (`restaurant`, `exitId`, `quantity`, `level`, `triggeringExitId`).

    Entrada: columnas `id`, `event_id`, `event_type`, `service`, `timestamp`, `tags`.
    El `timestamp` se convierte a datetime UTC aquí, antes de cualquier agrupación por día.
    """
    base_columns = ["id", "event_id", "event_type", "service", "timestamp"]
    if raw.empty:
        return pd.DataFrame({**{c: pd.Series(dtype=object) for c in base_columns}, **{f: pd.Series(dtype=object) for f in TAG_FIELDS}})
    tags = pd.json_normalize(raw["tags"].map(_as_dict).tolist()).reindex(columns=list(TAG_FIELDS))
    tags.index = raw.index
    flat = raw[base_columns].join(tags)
    return flat.assign(
        # `errors="coerce"`: un timestamp ilegible o fuera de rango (p. ej. año 2999) pasa a NaT y la cuarentena lo aparta.
        timestamp=pd.to_datetime(flat["timestamp"], utc=True, errors="coerce"),
        quantity=pd.to_numeric(flat["quantity"], errors="coerce"),
        exitId=pd.to_numeric(flat["exitId"], errors="coerce"),
        triggeringExitId=pd.to_numeric(flat["triggeringExitId"], errors="coerce"),
    )


def quarantine_events(events: pd.DataFrame, now: datetime, max_age: timedelta | None = MAX_EVENT_AGE) -> tuple[pd.DataFrame, int]:
    """Aparta los eventos con timestamp imposible (reloj del navegador desajustado, diseño §3.4).

    Devuelve `(aceptados, nº_en_cuarentena)`. `max_age=None` desactiva la regla de antigüedad: se usa
    en recálculos con rango explícito (backfill), donde el usuario pidió justamente datos antiguos.
    """
    if events.empty:
        return events, 0
    now_utc = pd.Timestamp(now).tz_convert("UTC") if pd.Timestamp(now).tzinfo else pd.Timestamp(now, tz="UTC")
    bad = events["timestamp"].isna() | (events["timestamp"] > now_utc + FUTURE_TOLERANCE)  # NaT = timestamp ilegible
    if max_age is not None:
        bad = bad | (events["timestamp"] < now_utc - max_age)
    return events[~bad], int(bad.sum())


def assign_buckets(events: pd.DataFrame, dim: pd.DataFrame) -> pd.DataFrame:
    """Asigna `restaurant` válido (o `UNATTRIBUTED`) y `report_date` en el día LOCAL del restaurante."""
    known = events["restaurant"].isin(dim["restaurant"]) & (events["restaurant"] != UNATTRIBUTED)
    restaurant = events["restaurant"].where(known, UNATTRIBUTED)
    zones = _zone_of(restaurant, dim)
    return events.assign(restaurant=restaurant, report_date=local_date(events["timestamp"], zones), unattributed=~known)


def dedupe_events(events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Deduplica por clave de negocio (capa 2 del diseño §5.1.4). Devuelve `(conservados, descartados)`.

    Claves: `exitId` para `outbound_order_created`; (`triggeringExitId`, `level`) para
    `stock_threshold_triggered`; el resto (y los eventos sin clave de negocio) por `event_id`.
    Si frontend y backend emiten la misma orden, se conserva la del backend.
    """
    if events.empty:
        return events, events
    event_key = "event:" + events["event_id"].astype("string")
    exit_key = "exit:" + events["exitId"].astype("Int64").astype("string")
    trigger_key = (
        "trigger:" + events["triggeringExitId"].astype("Int64").astype("string") + ":" + events["level"].astype("string")
    )
    key = event_key.mask((events["event_type"] == OUTBOUND_ORDER_CREATED) & events["exitId"].notna(), exit_key)
    key = key.mask(
        (events["event_type"] == STOCK_THRESHOLD_TRIGGERED) & events["triggeringExitId"].notna() & events["level"].notna(),
        trigger_key,
    )
    ordered = (
        events.assign(dedupe_key=key, source_priority=events["service"].map(SOURCE_PRIORITY).fillna(9))
        .sort_values(["source_priority", "id"])
    )
    duplicated = ordered.duplicated(subset=["event_type", "dedupe_key"], keep="first")
    kept = ordered[~duplicated].drop(columns=["dedupe_key", "source_priority"]).sort_values("id")
    dropped = ordered[duplicated].drop(columns=["dedupe_key", "source_priority"]).sort_values("id")
    return kept, dropped


# --------------------------------------------------------------------------- #
# 2 · Qué cubos hay que recalcular
# --------------------------------------------------------------------------- #
def plan_buckets(
    new_events: pd.DataFrame,
    dim: pd.DataFrame,
    now: datetime,
    lookback_days: int,
    window: tuple[date, date] | None = None,
) -> pd.DataFrame:
    """Cubos (`report_date`, `restaurant`) afectados (diseño §5.1.1).

    - Incremental: cubos de los eventos nuevos (de CUALQUIER antigüedad: un evento tardío reabre un
      día ya publicado) ∪ los últimos `lookback_days` días locales de los 14 restaurantes (K6 depende
      del stock, que cambia aunque no haya eventos).
    - Rango explícito `window=(desde, hasta)` (disparo manual / backfill): todos los días del rango para
      los 14 restaurantes, más los cubos con eventos dentro del rango (p. ej. `UNATTRIBUTED`).
    """
    real = dim[dim["restaurant"] != UNATTRIBUTED][["restaurant", "timezone"]]
    from_events = new_events[BUCKET] if not new_events.empty else pd.DataFrame({c: pd.Series(dtype=object) for c in BUCKET})
    now_ts = pd.Timestamp(now).tz_convert("UTC") if pd.Timestamp(now).tzinfo else pd.Timestamp(now, tz="UTC")

    if window is not None:
        days = pd.DataFrame({"report_date": pd.date_range(window[0], window[1], freq="D").date})
        from_events = from_events[from_events["report_date"].between(window[0], window[1])]
        scheduled = real[["restaurant"]].merge(days, how="cross")
    else:
        today = real["timezone"].map(lambda zone: now_ts.tz_convert(zone).date())
        offsets = pd.DataFrame({"offset": np.arange(max(lookback_days, 1))})
        scheduled = real[["restaurant"]].assign(today=pd.to_datetime(today)).merge(offsets, how="cross")
        scheduled = scheduled.assign(report_date=(scheduled["today"] - pd.to_timedelta(scheduled["offset"], unit="D")).dt.date)

    return pd.concat([from_events, scheduled[BUCKET]]).drop_duplicates().sort_values(BUCKET).reset_index(drop=True)


def bucket_time_range(buckets: pd.DataFrame, dim: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Rango UTC `[inicio, fin)` que cubre todos los cubos: de la primera medianoche local a la última."""
    zones = _zone_of(buckets["restaurant"], dim)
    days = buckets["report_date"]
    starts = _local_midnight_utc(days, zones)
    ends = _local_midnight_utc(pd.to_datetime(days) + pd.Timedelta(days=1), zones)
    return starts.min(), ends.max()


# --------------------------------------------------------------------------- #
# 3 · Calcular K1–K6
# --------------------------------------------------------------------------- #
def _ingredients_at_risk(buckets: pd.DataFrame, movements: pd.DataFrame, dim: pd.DataFrame, low: float, critical: float) -> pd.DataFrame:
    """K6: nº de insumos cuyo stock AL CIERRE del día local es <= `low` (y de ellos <= `critical`).

    Stock = Σ entradas − Σ salidas con `ts` anterior a la medianoche local del día siguiente.
    Solo cuentan insumos que ya habían tenido algún movimiento para ese cierre (no existían antes → no cuentan).
    """
    columns = BUCKET + ["ingredients_at_risk_eod", "ingredients_critical_eod"]
    if movements.empty or buckets.empty:
        return pd.DataFrame({c: pd.Series(dtype=object) for c in columns})
    cutoff = _local_midnight_utc(
        (pd.to_datetime(buckets["report_date"]) + pd.Timedelta(days=1)).reset_index(drop=True),
        _zone_of(buckets["restaurant"], dim).reset_index(drop=True),
    )
    cutoffs = buckets.reset_index(drop=True).assign(cutoff=cutoff)
    joined = cutoffs.merge(movements, on="restaurant")
    joined = joined[joined["ts"] < joined["cutoff"]]
    stock = joined.groupby(BUCKET + ["ingredient_id"], as_index=False)["delta"].sum()
    stock = stock.assign(at_risk=stock["delta"] <= low, critical=stock["delta"] <= critical)
    return stock.groupby(BUCKET, as_index=False).agg(
        ingredients_at_risk_eod=("at_risk", "sum"), ingredients_critical_eod=("critical", "sum")
    )


def _pct(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """numerador ÷ denominador × 100 redondeado a 2 decimales; NaN si el denominador es 0."""
    return (numerator / denominator.where(denominator > 0) * 100).round(2)


def prepare_events(raw_events: pd.DataFrame, dim: pd.DataFrame, now: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aplana el payload, asigna el día local de cada restaurante y deduplica. Devuelve `(conservados, descartados)`.

    En el recálculo solo se descartan los timestamps del futuro (`max_age=None`): los cubos se recalculan enteros.
    """
    events, _ = quarantine_events(flatten_events(raw_events), now, max_age=None)  # antes del día local: NaT no tiene día
    return dedupe_events(assign_buckets(events, dim))


def _in_buckets(events: pd.DataFrame, buckets: pd.DataFrame, event_type: str) -> pd.DataFrame:
    """Eventos de un tipo que caen en los cubos (restaurante, día local) a recalcular."""
    if events.empty:
        return events
    joined = events.merge(buckets, on=BUCKET)
    return joined[joined["event_type"] == event_type]


def _with_buckets(buckets: pd.DataFrame, part: pd.DataFrame) -> pd.DataFrame:
    """Cada KPI devuelve UNA fila por cubo (los cubos sin eventos valen 0), para poder ensamblarlos sin huecos."""
    return buckets.merge(part, on=BUCKET, how="left")


def _order_totals(orders: pd.DataFrame) -> pd.DataFrame:
    return orders.groupby(BUCKET, as_index=False).agg(outbound_orders=("event_id", "size"), units_issued=("quantity", "sum"))


def kpi_outbound_orders_and_units_issued(events: pd.DataFrame, buckets: pd.DataFrame) -> pd.DataFrame:
    """K1 `outbound_orders` y K2 `units_issued`: órdenes de salida (una por `exitId`) y Σ `quantity`, por cubo."""
    orders = _in_buckets(events, buckets, OUTBOUND_ORDER_CREATED)
    result = _with_buckets(buckets, _order_totals(orders))
    result["outbound_orders"] = pd.to_numeric(result["outbound_orders"], errors="coerce").fillna(0).astype(int)
    result["units_issued"] = pd.to_numeric(result["units_issued"], errors="coerce").fillna(0.0).astype(float).round(4)
    return result


def kpi_spoilage_rate_pct(events: pd.DataFrame, exits: pd.DataFrame, buckets: pd.DataFrame) -> pd.DataFrame:
    """K3 `spoilage_units` y `spoilage_rate_pct`: unidades de salidas cuya razón empieza por «Merma» ÷ `units_issued` × 100.

    La razón se lee de `ingredient_exits` (por `exitId`) solo para clasificar; el texto nunca sale de esta función.
    """
    orders = _in_buckets(events, buckets, OUTBOUND_ORDER_CREATED)
    if not orders.empty:
        orders = orders.merge(exits[["exit_id", "reason"]], left_on="exitId", right_on="exit_id", how="left")
    else:
        orders = orders.assign(reason=pd.Series(dtype=object))
    is_spoilage = orders["reason"].fillna("").astype(str).str.strip().str.lower().str.startswith(SPOILAGE_PREFIX)
    orders = orders.assign(spoilage_quantity=orders["quantity"].where(is_spoilage, 0.0))
    totals = orders.groupby(BUCKET, as_index=False).agg(units_issued=("quantity", "sum"), spoilage_units=("spoilage_quantity", "sum"))
    result = _with_buckets(buckets, totals)
    units = pd.to_numeric(result["units_issued"], errors="coerce").fillna(0.0).astype(float).round(4)
    spoiled = pd.to_numeric(result["spoilage_units"], errors="coerce").fillna(0.0).astype(float).round(4)
    return result[BUCKET].assign(spoilage_units=spoiled, spoilage_rate_pct=_pct(spoiled, units))


def kpi_stock_alerts(events: pd.DataFrame, buckets: pd.DataFrame) -> pd.DataFrame:
    """K4 `stock_alerts_low` / `stock_alerts_critical`: cruces de umbral hacia abajo (ya deduplicados por exitId+nivel)."""
    alerts = _in_buckets(events, buckets, STOCK_THRESHOLD_TRIGGERED)
    counted = alerts.assign(is_low=alerts["level"] == "low", is_critical=alerts["level"] == "critical").groupby(
        BUCKET, as_index=False
    ).agg(stock_alerts_low=("is_low", "sum"), stock_alerts_critical=("is_critical", "sum"))
    result = _with_buckets(buckets, counted)
    for column in ("stock_alerts_low", "stock_alerts_critical"):
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0).astype(int)
    return result


def kpi_validation_rejection_rate_pct(events: pd.DataFrame, buckets: pd.DataFrame) -> pd.DataFrame:
    """K5 `validation_failures` y `validation_rejection_rate_pct`: rechazos ÷ (órdenes + rechazos) × 100."""
    failures = _in_buckets(events, buckets, INVENTORY_VALIDATION_FAILED)
    counted = failures.groupby(BUCKET, as_index=False).agg(validation_failures=("event_id", "size"))
    rejected = pd.to_numeric(_with_buckets(buckets, counted)["validation_failures"], errors="coerce").fillna(0).astype(int)
    orders = kpi_outbound_orders_and_units_issued(events, buckets)["outbound_orders"]
    return buckets[BUCKET].assign(validation_failures=rejected, validation_rejection_rate_pct=_pct(rejected, orders + rejected))


def kpi_ingredients_at_risk_eod(buckets: pd.DataFrame, movements: pd.DataFrame, dim: pd.DataFrame, low: float, critical: float) -> pd.DataFrame:
    """K6 `ingredients_at_risk_eod` / `ingredients_critical_eod`: insumos con stock al cierre local ≤ umbral."""
    result = _with_buckets(buckets, _ingredients_at_risk(buckets, movements, dim, low, critical))
    for column in ("ingredients_at_risk_eod", "ingredients_critical_eod"):
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0).astype(int)
    return result


def assemble_daily_kpis(
    buckets: pd.DataFrame,
    kpi_parts: list[pd.DataFrame],
    exits: pd.DataFrame,
    dropped: pd.DataFrame,
    dim: pd.DataFrame,
    source_max_event_id: int,
) -> pd.DataFrame:
    """Une los KPIs (una fila por cubo), añade las columnas de calidad y el `kpi_hash`. Determinista."""
    exits_local = exits.assign(report_date=local_date(exits["created_at"], _zone_of(exits["restaurant"], dim))) if not exits.empty else exits.assign(report_date=pd.Series(dtype=object))
    real_exits = exits_local.groupby(BUCKET, as_index=False).agg(real_exits=("exit_id", "size"))
    deduplicated = dropped.groupby(BUCKET, as_index=False).agg(events_deduplicated=("event_id", "size")) if not dropped.empty else pd.DataFrame({c: pd.Series(dtype=object) for c in BUCKET + ["events_deduplicated"]})

    result = buckets.copy()
    for part in (*kpi_parts, real_exits, deduplicated):
        result = result.merge(part, on=BUCKET, how="left")
    for column in ("real_exits", "events_deduplicated"):
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0).astype(int)

    result["telemetry_coverage_pct"] = _pct(result["outbound_orders"], result["real_exits"])
    # capture_health: distingue «no hubo salidas» de «hubo salidas pero la telemetría no las vio» (diseño §10.4)
    result["capture_health"] = np.select(
        [result["outbound_orders"] > 0, result["real_exits"] > 0],
        [CAPTURE_OK, CAPTURE_GAP],
        default=CAPTURE_REAL_ZERO,
    )
    result["kpi_hash"] = result[KPI_VALUE_COLUMNS].apply(
        lambda row: hashlib.sha256(json.dumps([_native(v) for v in row], sort_keys=True).encode()).hexdigest()[:32], axis=1
    )
    result["source_max_event_id"] = int(source_max_event_id)
    return result.drop(columns=["real_exits"]).sort_values(BUCKET).reset_index(drop=True)


def compute_daily_kpis(
    events: pd.DataFrame,
    exits: pd.DataFrame,
    movements: pd.DataFrame,
    buckets: pd.DataFrame,
    dim: pd.DataFrame,
    dropped: pd.DataFrame,
    source_max_event_id: int,
    low: float = DEFAULT_LOW_THRESHOLD,
    critical: float = DEFAULT_CRITICAL_THRESHOLD,
) -> pd.DataFrame:
    """Una fila por cubo con K1–K6, columnas de calidad y `kpi_hash`: compone las funciones de arriba (misma lógica
    que las tasks del pipeline). Determinista: mismos datos → mismas filas.

    `events`: TODOS los eventos (ya aplanados, con cubo asignado y deduplicados) de los cubos a recalcular.
    `exits`: `ingredient_exits` del dominio (`exit_id`, `reason`, `created_at`, `restaurant`) → merma y cobertura.
    `movements`: entradas/salidas de stock (`ingredient_id`, `restaurant`, `ts`, `delta`) → K6.
    `dropped`: eventos descartados por la deduplicación → `events_deduplicated`.
    """
    parts = [
        kpi_outbound_orders_and_units_issued(events, buckets),
        kpi_spoilage_rate_pct(events, exits, buckets),
        kpi_stock_alerts(events, buckets),
        kpi_validation_rejection_rate_pct(events, buckets),
        kpi_ingredients_at_risk_eod(buckets, movements, dim, low, critical),
    ]
    return assemble_daily_kpis(buckets, parts, exits, dropped, dim, source_max_event_id)


# --------------------------------------------------------------------------- #
# 4 · Controles de calidad antes de cargar
# --------------------------------------------------------------------------- #
def validate_kpi_rows(rows: pd.DataFrame) -> list[str]:
    """Falla (`KpiValidationError`) si algún KPI es imposible; devuelve avisos no bloqueantes.

    Bloqueantes: valores negativos, porcentajes K3/K5 fuera de [0, 100], `critical` > `at_risk`.
    No bloqueante: cobertura > 100 % (hay duplicados que la deduplicación no atrapó; se avisa, no se oculta).
    """
    if rows.empty:
        return []
    problems: list[str] = []
    numeric = ["outbound_orders", "units_issued", "spoilage_units", "stock_alerts_low", "stock_alerts_critical",
               "validation_failures", "ingredients_at_risk_eod", "ingredients_critical_eod", "events_deduplicated"]
    for column in numeric:
        if (rows[column] < 0).any():
            problems.append(f"{column} tiene valores negativos")
    for column in ("spoilage_rate_pct", "validation_rejection_rate_pct"):
        if ((rows[column] < 0) | (rows[column] > 100)).any():
            problems.append(f"{column} fuera de [0, 100]")
    if (rows["ingredients_critical_eod"] > rows["ingredients_at_risk_eod"]).any():
        problems.append("ingredients_critical_eod mayor que ingredients_at_risk_eod")
    if (rows["spoilage_units"] > rows["units_issued"] + 1e-9).any():
        problems.append("spoilage_units mayor que units_issued")
    if problems:
        raise KpiValidationError("; ".join(problems))
    return [
        f"cobertura > 100 % en {int(((rows['telemetry_coverage_pct'] > 100)).sum())} cubo(s): posibles duplicados no atrapados"
    ] if (rows["telemetry_coverage_pct"] > 100).any() else []


# --------------------------------------------------------------------------- #
# 5 · Presentación (usado por la consulta de KPIs semanal)
# --------------------------------------------------------------------------- #
def aggregate_weekly(rows: pd.DataFrame) -> pd.DataFrame:
    """Agrega filas diarias a semanas (lunes) por restaurante, recalculando las tasas desde las sumas.

    Los conteos se suman; K3/K5/cobertura se RECALCULAN desde las sumas (no se promedian porcentajes);
    K6 toma el cierre del ÚLTIMO día de la semana; `capture_health` toma el peor valor de la semana.
    `telemetry_coverage_pct` queda en NULL en la vista semanal: el diario no guarda las salidas reales
    (solo el porcentaje ya redondeado), y reconstruirlas sumaría error de redondeo.
    """
    if rows.empty:
        return rows
    frame = rows.assign(week=(pd.to_datetime(rows["report_date"]) - pd.to_timedelta(pd.to_datetime(rows["report_date"]).dt.weekday, unit="D")).dt.date)
    health_rank = {CAPTURE_OK: 0, CAPTURE_REAL_ZERO: 1, CAPTURE_GAP: 2}
    frame = frame.assign(health_rank=frame["capture_health"].map(health_rank))
    last_day = frame.sort_values("report_date").groupby(["week", "restaurant"], as_index=False).last()[
        ["week", "restaurant", "country", "ingredients_at_risk_eod", "ingredients_critical_eod"]
    ]
    summed = frame.groupby(["week", "restaurant"], as_index=False).agg(
        outbound_orders=("outbound_orders", "sum"), units_issued=("units_issued", "sum"), spoilage_units=("spoilage_units", "sum"),
        stock_alerts_low=("stock_alerts_low", "sum"), stock_alerts_critical=("stock_alerts_critical", "sum"),
        validation_failures=("validation_failures", "sum"), events_deduplicated=("events_deduplicated", "sum"),
        health_rank=("health_rank", "max"), revision=("revision", "max"),
    )
    weekly = summed.merge(last_day, on=["week", "restaurant"])
    inverse = {rank: name for name, rank in health_rank.items()}
    weekly = weekly.assign(
        report_date=weekly["week"],
        spoilage_rate_pct=_pct(weekly["spoilage_units"], weekly["units_issued"]),
        validation_rejection_rate_pct=_pct(weekly["validation_failures"], weekly["outbound_orders"] + weekly["validation_failures"]),
        telemetry_coverage_pct=np.nan,
        capture_health=weekly["health_rank"].map(inverse),
    )
    return weekly.drop(columns=["week", "health_rank"]).sort_values(BUCKET).reset_index(drop=True)
