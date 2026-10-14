"""Pipeline resiliente «Desempeño de Inventario por Restaurante» (punto de entrada).

Implementa `data/pipelines/PIPELINE_DESIGN.md`: lee `telemetry_events` (solo lectura) y las tablas de
inventario, calcula los KPIs K1–K6 por restaurante y día local, y los carga de forma idempotente en
`reporting.restaurant_inventory_daily`. No toca `telemetry_events`, ni `analysis.py`, ni `GET /telemetry/report`.

    Extracción                              Transformación                 Carga (1 transacción)
    read_checkpoint → extract_telemetry_events → extract_domain_snapshot → transform_daily_kpis → validate_kpis → load_…

CÓMO EJECUTARLO (desde la raíz del monorepo, con `DATABASE_URL` en `services/api/.env` o en el entorno):

    python data/pipelines/pipeline.py                                   # corrida única (incremental desde el checkpoint)
    python data/pipelines/pipeline.py --date-from 2026-10-01 --date-to 2026-10-07   # recalcula un rango
    python data/pipelines/pipeline.py --serve                           # lo deja programado: todos los días 10:00 UTC (cron `0 10 * * *`)

Qué hace resiliente al pipeline (los cuatro requisitos del ticket):
1. Tolera fallos parciales: las tasks críticas se invocan con `return_state=True` y se registra el error
   estructurado en `reporting.pipeline_runs`; la task OPCIONAL (`export_eval_snapshot`) puede fallar sin
   interrumpir extract → transform → load.
2. Reintentos con espera en cada task que toca la base de datos (justificación en cada decorador).
3. Caché de 1 h en la transformación costosa: si ya corrió bien con los mismos datos, no se repite.
4. Se ejecuta como script (`if __name__ == "__main__"`) y también desde `services/reporting/` (disparo manual).
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

# Permite `python data/pipelines/pipeline.py`: al ejecutar un fichero, Python solo añade SU carpeta al
# path; el import absoluto `data.…` necesita la raíz del monorepo.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402
from prefect import flow, get_run_logger, task  # noqa: E402
from prefect.runtime import flow_run as flow_run_context  # noqa: E402

from data.pipelines.inventory_performance import db, queries, settings  # noqa: E402
from data.pipelines.inventory_performance.windows import resolve_window  # noqa: E402
from data.process import business_kpis as kpi  # noqa: E402

EVAL_OUTPUT = REPO_ROOT / "data" / "eval" / "inventory_performance_last_run.json"
UTC = timezone.utc


class PipelineStageError(RuntimeError):
    """Una task crítica agotó sus reintentos: se registra en el log de la corrida y el flow termina en Failed."""

    def __init__(self, stage: str, original: BaseException, retries: int):
        super().__init__(f"{stage}: {type(original).__name__}: {original}")
        self.stage, self.original, self.retries = stage, original, retries

    def as_entry(self) -> dict[str, Any]:
        return {"stage": self.stage, "type": type(self.original).__name__, "message": str(self.original), "retries_configured": self.retries, "severity": "error"}


# =========================================================================== #
# TASKS — una por etapa, cada una con inputs y outputs explícitos
# =========================================================================== #
@task(
    name="acquire_run_lock_and_start_run",
    # 2 reintentos × 5 s: es una escritura mínima en la BD; un corte de red de segundos se absorbe sin intervención humana.
    # Es seguro reintentar porque `start_run` es reentrante (si el run_id ya existe, no lo duplica).
    retries=2,
    retry_delay_seconds=5,
)
def acquire_run_lock_and_start_run(run_id: str, trigger: str, triggered_by: int | None, window_from: date | None, window_to: date | None) -> bool:
    """Control: crea el esquema `reporting` si falta, marca `crashed` las corridas muertas y toma el candado."""
    engine = db.get_engine()
    db.ensure_reporting_schema(engine)
    return db.start_run(engine, run_id, trigger, triggered_by, window_from, window_to, flow_run_context.id)


@task(
    name="read_checkpoint",
    retries=2,  # lectura idempotente de una fila: se puede repetir sin riesgo; 2 reintentos bastan para un corte breve
    retry_delay_seconds=5,
)
def read_checkpoint() -> int:
    """Extracción: último `telemetry_events.id` procesado por una carga confirmada."""
    return db.read_watermark(db.get_engine())


@task(
    name="extract_telemetry_events",
    # 3 reintentos con espera creciente (30 s, 2 min, 5 min): es una LECTURA, así que repetirla es siempre segura, y los
    # fallos típicos (Supabase reiniciando o saturado) se resuelven en minutos. Más de 3 solo retrasaría el aviso.
    retries=3,
    retry_delay_seconds=[30, 120, 300],
)
def extract_telemetry_events(last_event_id: int, window: tuple[date, date] | None) -> dict[str, Any]:
    """Extracción: eventos obligatorios nuevos (solo lectura), desde `checkpoint − solape` y hasta un tope congelado.

    Con un rango explícito se leen los eventos por `timestamp` del rango (±1 día por las zonas horarias) y el
    checkpoint no se tocará.
    """
    with db.get_engine().connect() as connection:
        max_event_id = queries.fetch_max_event_id(connection)
        if window is None:
            from_id = max(last_event_id - settings.WATERMARK_OVERLAP, 0)
            events = queries.fetch_events_since(connection, from_id, max_event_id, settings.PAGE_SIZE)
        else:
            from_id = None
            start = datetime.combine(window[0] - timedelta(days=1), time.min, tzinfo=UTC)
            end = datetime.combine(window[1] + timedelta(days=2), time.min, tzinfo=UTC)
            events = queries.fetch_events_in_range(connection, start, end, max_event_id)
    return {"events": events, "max_event_id": max_event_id, "from_id": from_id}


@task(
    name="extract_domain_snapshot",
    retries=3,  # mismo razonamiento que `extract_telemetry_events`: lecturas de solo lectura, seguras de repetir
    retry_delay_seconds=[30, 120, 300],
)
def extract_domain_snapshot(extraction: dict[str, Any], window: tuple[date, date] | None, now: datetime) -> dict[str, Any]:
    """Extracción: decide QUÉ cubos recalcular y lee de la fuente todo lo necesario para recalcularlos ENTEROS.

    Eventos nuevos → cubos afectados (+ ventana de retroceso) → todos los eventos de esos cubos, más las salidas
    de inventario (razón de merma, cobertura) y los movimientos de stock (K6). Calcula también `fingerprint`,
    la huella que usa la caché de la transformación.
    """
    with db.get_engine().connect() as connection:
        dim = queries.fetch_dim_restaurant(connection)
        fresh = kpi.flatten_events(extraction["events"])
        fresh, quarantined = kpi.quarantine_events(fresh, now, max_age=None if window else kpi.MAX_EVENT_AGE)
        fresh = kpi.assign_buckets(fresh, dim)
        buckets = kpi.plan_buckets(fresh, dim, now, settings.LOOKBACK_DAYS, window)
        ts_from, ts_to = kpi.bucket_time_range(buckets, dim)
        all_events = queries.fetch_events_in_range(connection, ts_from.to_pydatetime(), ts_to.to_pydatetime(), extraction["max_event_id"])
        exit_ids = kpi.flatten_events(all_events).query("event_type == @kpi.OUTBOUND_ORDER_CREATED")["exitId"].dropna().astype(int)
        restaurants = sorted(set(buckets["restaurant"]) - {kpi.UNATTRIBUTED})
        exits = queries.fetch_exits(connection, restaurants, ts_from.to_pydatetime(), ts_to.to_pydatetime(), exit_ids)
        movements = queries.fetch_stock_movements(connection, restaurants, ts_to.to_pydatetime())
        domain = queries.fetch_domain_fingerprint(connection)

    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "code": settings.CODE_VERSION, "thresholds": [settings.LOW_THRESHOLD, settings.CRITICAL_THRESHOLD],
                "max_event_id": extraction["max_event_id"], "buckets": [[str(d), r] for d, r in buckets.itertuples(index=False)],
                "domain": domain, "window": [str(d) for d in window] if window else None,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return {
        "dim": dim, "buckets": buckets, "events": all_events, "exits": exits, "movements": movements,
        "max_event_id": extraction["max_event_id"], "fingerprint": fingerprint,
        # Calidad de la entrada (diseño §3.4): cuarentena + eventos sin restaurante identificable.
        "rows_rejected": int(quarantined + fresh["unattributed"].sum()) if not fresh.empty else int(quarantined),
    }


def _transform_cache_key(context: Any, parameters: dict[str, Any]) -> str:
    """Define la CLAVE DE CACHÉ de cada task de transformación.

    La clave es el nombre de la task + la huella (`fingerprint`) de lo que alimenta el cálculo: versión del código,
    umbrales, tope de `telemetry_events.id`, lista de cubos, estado de las tablas de inventario y rango. Mismos datos
    y mismo código → misma clave → se reutiliza el resultado; en cuanto llega un evento nuevo, cambia el tope de id y la
    clave cambia sola, así que la caché NUNCA sirve números de datos viejos. (`run_id` y `computed_at` no entran:
    los estampa la carga, para que una corrida cacheada conserve su propio linaje).
    """
    return f"inventory-performance-{context.task.name}-{parameters['fingerprint']}"


# Todas las tasks de transformación comparten política: sin `retries` (son funciones deterministas y sin red; repetirlas
# daría el mismo resultado o el mismo error), caché de 1 h (requisito del ticket: «si una task ya corrió bien en la última
# hora, no repetirla») y resultado persistido en disco para poder reutilizarse en la siguiente corrida.
transformation_task = functools.partial(task, cache_key_fn=_transform_cache_key, cache_expiration=settings.CACHE_EXPIRATION, persist_result=True)


@transformation_task(name="prepare_telemetry_events")
def prepare_telemetry_events(snapshot: dict[str, Any], fingerprint: str) -> dict[str, pd.DataFrame]:
    """Transformación: aplana el payload, asigna el día local de cada restaurante y deduplica por clave de negocio."""
    kept, dropped = kpi.prepare_events(snapshot["events"], snapshot["dim"], datetime.now(UTC))
    return {"events": kept, "dropped": dropped}


@transformation_task(name="compute_outbound_orders_and_units_issued")
def compute_outbound_orders_and_units_issued(events: pd.DataFrame, buckets: pd.DataFrame, fingerprint: str) -> pd.DataFrame:
    """K1 `outbound_orders` y K2 `units_issued` por restaurante y día local."""
    return kpi.kpi_outbound_orders_and_units_issued(events, buckets)


@transformation_task(name="compute_spoilage_rate_pct")
def compute_spoilage_rate_pct(events: pd.DataFrame, exits: pd.DataFrame, buckets: pd.DataFrame, fingerprint: str) -> pd.DataFrame:
    """K3 `spoilage_rate_pct`: merma ÷ unidades emitidas × 100 (la razón «Merma…» se lee de `ingredient_exits`)."""
    return kpi.kpi_spoilage_rate_pct(events, exits, buckets)


@transformation_task(name="compute_stock_alerts")
def compute_stock_alerts(events: pd.DataFrame, buckets: pd.DataFrame, fingerprint: str) -> pd.DataFrame:
    """K4 `stock_alerts_low` / `stock_alerts_critical`: cruces de umbral hacia abajo (30 → low, 10 → critical)."""
    return kpi.kpi_stock_alerts(events, buckets)


@transformation_task(name="compute_validation_rejection_rate_pct")
def compute_validation_rejection_rate_pct(events: pd.DataFrame, buckets: pd.DataFrame, fingerprint: str) -> pd.DataFrame:
    """K5 `validation_rejection_rate_pct`: rechazos ÷ (órdenes + rechazos) × 100."""
    return kpi.kpi_validation_rejection_rate_pct(events, buckets)


@transformation_task(name="compute_ingredients_at_risk_eod")
def compute_ingredients_at_risk_eod(buckets: pd.DataFrame, movements: pd.DataFrame, dim: pd.DataFrame, fingerprint: str) -> pd.DataFrame:
    """K6 `ingredients_at_risk_eod` / `ingredients_critical_eod`: insumos con stock al cierre local ≤ 30 / ≤ 10."""
    return kpi.kpi_ingredients_at_risk_eod(buckets, movements, dim, settings.LOW_THRESHOLD, settings.CRITICAL_THRESHOLD)


@transformation_task(name="assemble_daily_kpis")
def assemble_daily_kpis(
    buckets: pd.DataFrame, kpi_parts: list[pd.DataFrame], exits: pd.DataFrame, dropped: pd.DataFrame, dim: pd.DataFrame,
    source_max_event_id: int, fingerprint: str,
) -> pd.DataFrame:
    """Une K1–K6 en una fila por restaurante y día, con cobertura, `capture_health` y `kpi_hash`."""
    return kpi.assemble_daily_kpis(buckets, kpi_parts, exits, dropped, dim, source_max_event_id)


@task(name="validate_kpis")  # sin reintentos: es determinista. Si falla, el flow NO carga (una carga mala es peor que ninguna).
def validate_kpis(rows: pd.DataFrame) -> list[str]:
    """Transformación: controles de calidad. Lanza `KpiValidationError` si algún KPI es imposible."""
    return kpi.validate_kpi_rows(rows)


@task(
    name="load_restaurant_inventory_daily",
    # 2 reintentos (10 s y 60 s): reintentar la carga es SEGURO porque es idempotente (upsert por clave natural +
    # recálculo completo + transacción única con el checkpoint): repetirla nunca duplica ni suma dos veces.
    retries=2,
    retry_delay_seconds=[10, 60],
)
def load_restaurant_inventory_daily(rows: pd.DataFrame, run_id: str, computed_at: datetime, watermark_to: int | None) -> dict[str, int]:
    """Carga: upsert + revisiones + checkpoint en una sola transacción (ver `db.load_daily_kpis`)."""
    return db.load_daily_kpis(db.get_engine(), rows, run_id, computed_at, watermark_to)


@task(
    name="export_eval_snapshot",
    # OPCIONAL / NO CRÍTICA: es una salida secundaria de validación en `data/eval/`. El flow la invoca con
    # `return_state=True`, así que si falla (disco lleno, permisos) se anota un aviso y el ETL principal sigue.
)
def export_eval_snapshot(rows: pd.DataFrame, run_id: str, summary: dict[str, Any], warnings: list[str]) -> str:
    """Opcional: escribe en `data/eval/` el resultado de la corrida (KPIs, salud de captura y avisos) para auditarla."""
    payload = {
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": summary,
        "capture_health": rows["capture_health"].value_counts().to_dict(),
        "warnings": warnings,
        "kpis": json.loads(rows.drop(columns=["kpi_hash"]).to_json(orient="records", date_format="iso")),
    }
    EVAL_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = EVAL_OUTPUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(EVAL_OUTPUT)  # reemplazo atómico: nunca queda un JSON a medias
    return str(EVAL_OUTPUT)


@task(
    name="finish_run",
    retries=2,  # cerrar el log es una escritura mínima y reentrante (el mismo UPDATE dos veces da el mismo estado)
    retry_delay_seconds=5,
)
def finish_run(run_id: str, status: str, stats: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    """Control: cierra la fila de `pipeline_runs` con estado final, contadores y errores (libera el candado)."""
    db.finish_run(db.get_engine(), run_id, status, stats, errors)


# =========================================================================== #
# FLOWS
# =========================================================================== #
def _run_stage(stage_task: Any, current_run_id: str, **parameters: Any) -> Any:
    """Invoca una task CRÍTICA con `return_state=True` y maneja su fallo de forma explícita.

    En vez de dejar que la excepción se propague sin contexto, se mira el estado final: si la task falló tras
    agotar sus reintentos, se convierte en un `PipelineStageError` con la etapa y el nº de reintentos, que el
    flow registra en `reporting.pipeline_runs.errors` antes de terminar en Failed.
    """
    try:
        db.heartbeat(db.get_engine(), current_run_id)  # latido: permite marcar `crashed` a las corridas colgadas
    except Exception:  # noqa: BLE001 — un latido perdido no debe tumbar la corrida
        get_run_logger().warning("no se pudo escribir el latido de %s", current_run_id)
    state = stage_task(**parameters, return_state=True)
    if state.is_failed():
        raise PipelineStageError(stage_task.name, state.result(raise_on_failure=False), stage_task.retries or 0)
    return state.result()


def _run_subflow(subflow: Any, **parameters: Any) -> Any:
    """Invoca un subflow CRÍTICO con `return_state=True` y devuelve su resultado.

    Si el subflow falló, su `PipelineStageError` (etapa + reintentos) se vuelve a lanzar tal cual para que el flow
    principal lo registre en `reporting.pipeline_runs`; cualquier otro error se envuelve con el nombre del subflow.
    """
    state = subflow(**parameters, return_state=True)
    if state.is_failed():
        problem = state.result(raise_on_failure=False)
        if isinstance(problem, PipelineStageError):
            raise problem
        raise PipelineStageError(subflow.name, problem if isinstance(problem, BaseException) else RuntimeError(str(problem)), 0)
    return state.result()


# =========================================================================== #
# SUBFLOWS — una fase cada uno, con inputs y outputs explícitos (sin variables globales entre ellos)
# =========================================================================== #
@flow(name="extract_inventory_telemetry", log_prints=True)
def extract_inventory_telemetry_flow(run_id: str, window: tuple[date, date] | None, now: datetime) -> dict[str, Any]:
    """Fase de EXTRACCIÓN: `telemetry_events` (solo lectura) + tablas de dominio de inventario.

    Entradas: `run_id` (para el latido), `window` (rango manual o `None` = incremental) y `now` (reloj de la corrida).
    Salida: `{"snapshot": <todo lo necesario para recalcular los cubos>, "from_id", "max_event_id", "rows_extracted"}`.
    """
    checkpoint = _run_stage(read_checkpoint, run_id)
    extraction = _run_stage(extract_telemetry_events, run_id, last_event_id=checkpoint, window=window)
    snapshot = _run_stage(extract_domain_snapshot, run_id, extraction=extraction, window=window, now=now)
    return {
        "snapshot": snapshot, "from_id": extraction["from_id"], "max_event_id": extraction["max_event_id"],
        "rows_extracted": int(len(extraction["events"])),
    }


@flow(name="compute_inventory_kpis", log_prints=True)
def compute_inventory_kpis_flow(run_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Fase de TRANSFORMACIÓN: eventos limpios → K1–K6 por restaurante y día local → controles de calidad.

    Entradas: `run_id` y el `snapshot` de la extracción. Sin base de datos: solo cálculo.
    Salida: `{"rows": <DataFrame con una fila por cubo>, "warnings", "rows_deduplicated", "buckets_recomputed"}`.
    Si `validate_kpis` falla, el subflow falla y NO se carga nada.
    """
    fingerprint, buckets, dim = snapshot["fingerprint"], snapshot["buckets"], snapshot["dim"]
    prepared = _run_stage(prepare_telemetry_events, run_id, snapshot=snapshot, fingerprint=fingerprint)
    events = prepared["events"]
    kpi_parts = [
        _run_stage(compute_outbound_orders_and_units_issued, run_id, events=events, buckets=buckets, fingerprint=fingerprint),
        _run_stage(compute_spoilage_rate_pct, run_id, events=events, exits=snapshot["exits"], buckets=buckets, fingerprint=fingerprint),
        _run_stage(compute_stock_alerts, run_id, events=events, buckets=buckets, fingerprint=fingerprint),
        _run_stage(compute_validation_rejection_rate_pct, run_id, events=events, buckets=buckets, fingerprint=fingerprint),
        _run_stage(compute_ingredients_at_risk_eod, run_id, buckets=buckets, movements=snapshot["movements"], dim=dim, fingerprint=fingerprint),
    ]
    rows = _run_stage(
        assemble_daily_kpis, run_id, buckets=buckets, kpi_parts=kpi_parts, exits=snapshot["exits"], dropped=prepared["dropped"],
        dim=dim, source_max_event_id=snapshot["max_event_id"], fingerprint=fingerprint,
    )
    warnings = _run_stage(validate_kpis, run_id, rows=rows)
    return {"rows": rows, "warnings": warnings, "rows_deduplicated": int(len(prepared["dropped"])), "buckets_recomputed": int(len(rows))}


@flow(name="load_restaurant_inventory_daily", log_prints=True)
def load_restaurant_inventory_daily_flow(run_id: str, rows: pd.DataFrame, computed_at: datetime, watermark_to: int | None) -> dict[str, int]:
    """Fase de CARGA en `reporting.restaurant_inventory_daily`: upsert + revisiones + checkpoint en UNA transacción.

    Entradas: filas de KPIs, instante de cálculo y checkpoint al que avanzar (`None` si fue un rango manual).
    Salida: `{"inserted", "updated", "unchanged"}`. Idempotente: repetirlo nunca duplica ni suma dos veces.
    """
    return _run_stage(load_restaurant_inventory_daily, run_id, rows=rows, run_id=run_id, computed_at=computed_at, watermark_to=watermark_to)


@flow(name="export_inventory_validation_snapshot", log_prints=True)
def export_inventory_validation_snapshot_flow(run_id: str, rows: pd.DataFrame, summary: dict[str, Any], warnings: list[str]) -> str:
    """Subflow OPCIONAL: escribe en `data/eval/` el resultado de la corrida para auditarla. Devuelve la ruta del fichero.

    El flow principal lo invoca con `return_state=True`: si falla (disco lleno, permisos) solo se anota un aviso.
    """
    return export_eval_snapshot(rows, run_id, summary, warnings)


# =========================================================================== #
# FLOW PRINCIPAL — solo coordina los subflows y registra la corrida; no contiene la lógica de negocio
# =========================================================================== #
@flow(name="inventory_performance_daily", log_prints=True)
def inventory_performance_daily_flow(
    trigger: str = "cron",
    triggered_by: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Flow principal: extracción → transformación → carga (subflows), con la corrida en `reporting.pipeline_runs`.

    `trigger`: `cron` | `manual` | `backfill`. `date_from`/`date_to` recalculan un rango (sin ellas, incremental).
    Si un subflow crítico falla, la corrida se cierra como `failed` (con el error estructurado) y el flow termina
    en Failed; si solo falla el subflow opcional, la corrida termina `completed` con un aviso.
    """
    logger = get_run_logger()
    run_id = run_id or str(uuid4())
    window = resolve_window(date_from, date_to)
    now = datetime.now(UTC)

    if not acquire_run_lock_and_start_run(run_id, trigger, triggered_by, window[0] if window else None, window[1] if window else None):
        logger.warning("Ya hay una corrida activa: esta (%s) queda registrada como skipped_locked", run_id)
        return {"run_id": run_id, "status": "skipped_locked"}

    stats: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []
    loaded: dict[str, int] = {"inserted": 0, "updated": 0, "unchanged": 0}
    failure: PipelineStageError | None = None
    try:
        extracted = _run_subflow(extract_inventory_telemetry_flow, run_id=run_id, window=window, now=now)
        computed = _run_subflow(compute_inventory_kpis_flow, run_id=run_id, snapshot=extracted["snapshot"])
        warnings = computed["warnings"]
        # Con rango explícito el checkpoint NO avanza: recalcular el pasado no debe saltarse eventos nuevos.
        watermark_to = None if window else extracted["max_event_id"]
        loaded = _run_subflow(load_restaurant_inventory_daily_flow, run_id=run_id, rows=computed["rows"], computed_at=now, watermark_to=watermark_to)
        stats = {
            "watermark_from": extracted["from_id"], "watermark_to": extracted["max_event_id"],
            "rows_extracted": extracted["rows_extracted"], "rows_deduplicated": computed["rows_deduplicated"],
            "rows_rejected": extracted["snapshot"]["rows_rejected"], "buckets_recomputed": computed["buckets_recomputed"],
            "rows_inserted": loaded["inserted"], "rows_updated": loaded["updated"],
        }
        # Subflow OPCIONAL con return_state=True: el ETL principal ya terminó; si esto falla, la corrida sigue `completed`.
        export_state = export_inventory_validation_snapshot_flow(
            run_id=run_id, rows=computed["rows"], summary={**stats, "unchanged": loaded["unchanged"]}, warnings=warnings, return_state=True
        )
        if export_state.is_failed():
            problem = export_state.result(raise_on_failure=False)
            errors.append({"stage": "export_inventory_validation_snapshot", "type": type(problem).__name__, "message": str(problem), "severity": "warning"})
            logger.warning("export_inventory_validation_snapshot falló (subflow opcional): %s — el pipeline continúa", problem)
        errors.extend({"stage": "validate_kpis", "type": "Warning", "message": message, "severity": "warning"} for message in warnings)
        status = "completed"
    except PipelineStageError as error:
        errors.append(error.as_entry())
        status, failure = "failed", error
    except Exception as error:  # noqa: BLE001 — cualquier otro error también debe quedar en el log de la corrida
        failure = PipelineStageError("flow", error, 0)
        errors.append(failure.as_entry())
        status = "failed"

    closing = finish_run(run_id, status, stats, errors, return_state=True)
    if closing.is_failed():  # no se pierde el error original por no poder cerrar el log
        logger.error("no se pudo cerrar el log de la corrida %s (quedará `running` y se marcará crashed por latido)", run_id)
    if failure is not None:
        raise failure
    return {
        "run_id": run_id, "status": status, **stats, "unchanged": loaded["unchanged"], "warnings": warnings,
        "optional_failures": [entry["stage"] for entry in errors if entry["stage"] == "export_inventory_validation_snapshot"],
    }


@flow(name="inventory_performance_backfill", log_prints=True)
def inventory_performance_backfill_flow(date_from: date, date_to: date, triggered_by: int | None = None) -> dict[str, Any]:
    """Flow de recuperación (diseño §8.1): reprocesa un rango de días con exactamente el mismo código."""
    return inventory_performance_daily_flow(trigger="backfill", triggered_by=triggered_by, date_from=date_from, date_to=date_to)


# =========================================================================== #
# CLI — `python data/pipelines/pipeline.py`
# =========================================================================== #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline «Desempeño de Inventario por Restaurante» (K1–K6 → reporting.restaurant_inventory_daily)")
    parser.add_argument("--date-from", type=date.fromisoformat, help="inicio (YYYY-MM-DD) de un recálculo por rango")
    parser.add_argument("--date-to", type=date.fromisoformat, help="fin (YYYY-MM-DD) del recálculo por rango")
    parser.add_argument("--trigger", choices=("manual", "cron", "backfill"), default="manual", help="origen que queda en el log (por defecto: manual)")
    parser.add_argument("--serve", action="store_true", help=f"deja el flow programado con cron `{settings.CRON_SCHEDULE}` (UTC) en vez de correr una vez")
    args = parser.parse_args(argv)

    if args.serve:
        inventory_performance_daily_flow.serve(name="production", cron=settings.CRON_SCHEDULE, parameters={"trigger": "cron"})
        return 0
    try:
        result = inventory_performance_daily_flow(trigger=args.trigger, date_from=args.date_from, date_to=args.date_to)
    except Exception as error:  # noqa: BLE001 — la CLI traduce el fallo en código de salida distinto de cero
        print(f"El pipeline falló: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
