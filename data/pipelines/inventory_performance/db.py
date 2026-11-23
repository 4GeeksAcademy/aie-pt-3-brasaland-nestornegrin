"""Acceso a la base de datos del pipeline: conexión, esquema `reporting`, checkpoint y log de corridas.

Solo ESCRIBE en el esquema `reporting` (diseño §8.3, menor privilegio): `telemetry_events` y las tablas de
inventario se leen en `queries.py` y jamás se modifican. Este módulo NO importa nada de `services/`
(diseño §9.3: `data/pipelines/` no depende de `services/`); la API le pasa su propio `engine` cuando
llama a `api.py`, y el flow crea el suyo desde `DATABASE_URL`.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from data.pipelines.inventory_performance import settings

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_SQL = REPO_ROOT / "services" / "api" / "migrations" / "002_create_reporting_schema.sql"

DAILY_TABLE = "reporting.restaurant_inventory_daily"
# Orden fijo de columnas de la tabla de destino (el mismo del DDL).
DAILY_COLUMNS = [
    "report_date", "restaurant", "outbound_orders", "units_issued", "spoilage_units", "spoilage_rate_pct",
    "stock_alerts_low", "stock_alerts_critical", "validation_failures", "validation_rejection_rate_pct",
    "ingredients_at_risk_eod", "ingredients_critical_eod", "telemetry_coverage_pct", "events_deduplicated",
    "capture_health", "source_max_event_id", "kpi_hash", "revision", "computed_at", "run_id",
]
LOAD_LOCK_KEY = "reporting.inventory_performance_daily.load"

_schema_ready = threading.Event()


# --------------------------------------------------------------------------- #
# Conexión
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Engine del pipeline, creado desde `DATABASE_URL` (la misma variable que usa la API)."""
    for candidate in (REPO_ROOT / ".env", REPO_ROOT / "services" / "api" / ".env"):
        if candidate.exists():
            load_dotenv(candidate)
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Falta DATABASE_URL (la cadena de conexión de Supabase). Defínela en services/api/.env o en el entorno.")
    return create_engine(url, pool_pre_ping=True)


def ensure_reporting_schema(engine: Engine) -> None:
    """Aplica `services/api/migrations/002_create_reporting_schema.sql` (idempotente) una vez por proceso."""
    if _schema_ready.is_set():
        return
    with engine.begin() as connection:
        connection.exec_driver_sql(SCHEMA_SQL.read_text(encoding="utf-8"))
    _schema_ready.set()


def reset_schema_cache() -> None:
    """Solo para tests: olvida que el esquema ya se aplicó."""
    _schema_ready.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Checkpoint
# --------------------------------------------------------------------------- #
def read_watermark(engine: Engine, pipeline_name: str = settings.PIPELINE_NAME) -> int:
    """Último `telemetry_events.id` procesado por una carga CONFIRMADA (0 si es la primera corrida)."""
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO reporting.pipeline_watermarks (pipeline_name, last_event_id) VALUES (:name, 0) ON CONFLICT DO NOTHING"),
            {"name": pipeline_name},
        )
        return int(connection.execute(text("SELECT last_event_id FROM reporting.pipeline_watermarks WHERE pipeline_name = :name"), {"name": pipeline_name}).scalar_one())


# --------------------------------------------------------------------------- #
# Log de ejecución (reporting.pipeline_runs, diseño §7.2)
# --------------------------------------------------------------------------- #
def mark_stale_runs_crashed(connection: Connection, pipeline_name: str) -> int:
    """Una corrida `running` sin latido reciente murió sin cerrarse: se marca `crashed` (diseño §10.10)."""
    result = connection.execute(
        text(
            """
            UPDATE reporting.pipeline_runs
               SET status = 'crashed', finished_at = now(),
                   errors = errors || CAST(:note AS jsonb)
             WHERE pipeline_name = :name AND status = 'running'
               AND heartbeat_at < now() - make_interval(secs => :timeout)
            """
        ),
        {
            "name": pipeline_name,
            "timeout": settings.HEARTBEAT_TIMEOUT.total_seconds(),
            "note": json.dumps([{"stage": "heartbeat", "type": "HeartbeatExpired", "message": "la corrida dejó de dar señales de vida y se marcó crashed"}]),
        },
    )
    return result.rowcount


def start_run(
    engine: Engine,
    run_id: str,
    trigger: str,
    triggered_by: int | None,
    window_from: date | None,
    window_to: date | None,
    prefect_flow_run_id: str | None,
    pipeline_name: str = settings.PIPELINE_NAME,
) -> bool:
    """Registra el inicio de la corrida y toma el «candado»: True si esta corrida puede ejecutar.

    El candado es el índice único parcial `ux_pipeline_runs_one_running`: como máximo UNA fila `running`.
    Si otra corrida está activa, el INSERT viola el índice y esta corrida queda registrada como
    `skipped_locked` (no hace nada más). Es reentrante: si `run_id` ya existe (reintento de la task),
    devuelve si sigue `running`.
    """
    params = {
        "run_id": run_id, "name": pipeline_name, "trigger": trigger, "triggered_by": triggered_by, "started": _now(),
        "window_from": window_from, "window_to": window_to, "code_version": settings.CODE_VERSION, "flow_run": prefect_flow_run_id,
    }
    insert = """
        INSERT INTO reporting.pipeline_runs
            (run_id, pipeline_name, trigger, triggered_by, started_at, status, window_from, window_to, code_version, prefect_flow_run_id, heartbeat_at, finished_at)
        VALUES (:run_id, :name, :trigger, :triggered_by, :started, :status, :window_from, :window_to, :code_version, :flow_run, :started, :finished)
    """
    with engine.begin() as connection:
        existing = connection.execute(text("SELECT status FROM reporting.pipeline_runs WHERE run_id = :run_id"), {"run_id": run_id}).scalar()
        if existing is not None:
            return existing == "running"
        mark_stale_runs_crashed(connection, pipeline_name)
    try:
        with engine.begin() as connection:
            connection.execute(text(insert), {**params, "status": "running", "finished": None})
        return True
    except IntegrityError:  # otra corrida `running` ya ocupa el candado
        with engine.begin() as connection:
            connection.execute(text(insert), {**params, "status": "skipped_locked", "finished": _now()})
        return False


def heartbeat(engine: Engine, run_id: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE reporting.pipeline_runs SET heartbeat_at = now() WHERE run_id = :run_id AND status = 'running'"), {"run_id": run_id})


def finish_run(engine: Engine, run_id: str, status: str, stats: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    """Cierra la corrida con su estado final, contadores y errores estructurados (libera el candado)."""
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE reporting.pipeline_runs
                   SET status = :status, finished_at = now(), heartbeat_at = now(),
                       watermark_from = :watermark_from, watermark_to = :watermark_to,
                       rows_extracted = :rows_extracted, rows_deduplicated = :rows_deduplicated, rows_rejected = :rows_rejected,
                       buckets_recomputed = :buckets_recomputed, rows_inserted = :rows_inserted, rows_updated = :rows_updated,
                       errors = CAST(:errors AS jsonb)
                 WHERE run_id = :run_id
                """
            ),
            {
                "run_id": run_id, "status": status, "errors": json.dumps(errors, default=str),
                **{key: stats.get(key) for key in ("watermark_from", "watermark_to")},
                **{key: int(stats.get(key) or 0) for key in ("rows_extracted", "rows_deduplicated", "rows_rejected", "buckets_recomputed", "rows_inserted", "rows_updated")},
            },
        )


# --------------------------------------------------------------------------- #
# Carga idempotente (diseño §5.1 y §7.1)
# --------------------------------------------------------------------------- #
_UPSERT = f"""
    INSERT INTO {DAILY_TABLE} AS t ({", ".join(DAILY_COLUMNS)})
    VALUES ({", ".join(":" + column for column in DAILY_COLUMNS)})
    ON CONFLICT (report_date, restaurant) DO UPDATE SET
        {", ".join(f"{c} = EXCLUDED.{c}" for c in DAILY_COLUMNS if c not in ("report_date", "restaurant", "revision"))},
        revision = t.revision + 1
    WHERE t.kpi_hash IS DISTINCT FROM EXCLUDED.kpi_hash
      AND EXCLUDED.source_max_event_id >= t.source_max_event_id
"""
_ARCHIVE = f"""
    INSERT INTO {DAILY_TABLE}_revisions ({", ".join(DAILY_COLUMNS)})
    VALUES ({", ".join(":" + column for column in DAILY_COLUMNS)})
"""


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Filas con NaN/NA → None y tipos nativos (psycopg2 no adapta numpy)."""
    cleaned = frame.astype(object).where(frame.notna(), None)
    return [{key: (value.item() if hasattr(value, "item") else value) for key, value in row.items()} for row in cleaned.to_dict("records")]


def _advance_watermark(connection: Connection, pipeline_name: str, watermark_to: int) -> None:
    """Avanza el checkpoint SIN retroceder nunca (GREATEST), dentro de la misma transacción de la carga."""
    connection.execute(
        text("UPDATE reporting.pipeline_watermarks SET last_event_id = GREATEST(last_event_id, :to), updated_at = now() WHERE pipeline_name = :name"),
        {"name": pipeline_name, "to": watermark_to},
    )


def load_daily_kpis(
    engine: Engine,
    rows: pd.DataFrame,
    run_id: str,
    computed_at: datetime,
    watermark_to: int | None,
    pipeline_name: str = settings.PIPELINE_NAME,
) -> dict[str, int]:
    """UPSERT idempotente + revisiones + checkpoint en UNA transacción.

    1. Candado de transacción (`pg_advisory_xact_lock`): dos cargas nunca se pisan. Se libera solo al
       terminar la transacción, por lo que funciona también a través del pooler de Supabase.
    2. Lee las filas ya publicadas de esos cubos y las compara por `kpi_hash`.
    3. Guarda el valor anterior de las filas que cambian en `…_revisions` (auditoría de eventos tardíos).
    4. Inserta las filas nuevas y actualiza las cambiadas (`revision + 1`); las idénticas NO se tocan.
    5. Avanza el checkpoint solo si `watermark_to` no es None (en un recálculo por rango no se avanza).

    Si cualquier paso falla, la transacción se revierte entera: ni filas a medias ni checkpoint adelantado.
    """
    stamped = rows.assign(computed_at=computed_at, run_id=run_id, revision=1)
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": LOAD_LOCK_KEY})
        existing = pd.DataFrame(columns=DAILY_COLUMNS)
        if not stamped.empty:
            existing = pd.read_sql(
                text(f"SELECT {', '.join(DAILY_COLUMNS)} FROM {DAILY_TABLE} WHERE report_date BETWEEN :lo AND :hi FOR UPDATE"),
                connection,
                params={"lo": stamped["report_date"].min(), "hi": stamped["report_date"].max()},
            )
        merged = stamped.merge(
            existing[["report_date", "restaurant", "kpi_hash", "source_max_event_id"]].rename(
                columns={"kpi_hash": "old_hash", "source_max_event_id": "old_max_event_id"}
            ),
            on=["report_date", "restaurant"],
            how="left",
        )
        is_new = merged["old_hash"].isna()
        # Cambia = hay fila previa, la huella difiere y la corrida no es MÁS VIEJA que la que la publicó.
        is_changed = ~is_new & (merged["old_hash"] != merged["kpi_hash"]) & (merged["source_max_event_id"] >= pd.to_numeric(merged["old_max_event_id"], errors="coerce").fillna(-1))
        changed_keys = merged.loc[is_changed, ["report_date", "restaurant"]]
        superseded = existing.merge(changed_keys, on=["report_date", "restaurant"])
        if not superseded.empty:
            connection.execute(text(_ARCHIVE), _records(superseded[DAILY_COLUMNS]))
        to_write = stamped[(is_new | is_changed).to_numpy()]
        if not to_write.empty:
            connection.execute(text(_UPSERT), _records(to_write[DAILY_COLUMNS]))
        if watermark_to is not None:
            _advance_watermark(connection, pipeline_name, int(watermark_to))
    return {"inserted": int(is_new.sum()), "updated": int(is_changed.sum()), "unchanged": int(len(merged) - is_new.sum() - is_changed.sum())}
