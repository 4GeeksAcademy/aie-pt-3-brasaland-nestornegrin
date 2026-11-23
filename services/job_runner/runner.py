"""Máquina de estados de `public.job_runs`: crear, actualizar y consultar ejecuciones de un job (DEV-53).

    pending → processing → completed
                        ↘ failed

Reglas que este módulo hace cumplir (y que `scripts/nightly_export.py` solo orquesta):

* `processing` ES el lock distribuido. No hay otra tabla, columna ni flag: `mark_processing` hace
  `UPDATE … SET status='processing' WHERE id=… AND status='pending'` y el índice único parcial
  `ux_job_runs_one_processing` (migración 003) deja pasar a UNA sola fila por `job_name`. Quien pierde la carrera
  recibe `False` (nunca una excepción) y debe abortar en silencio.
* `completed`/`failed` liberan el lock (la fila deja de estar `processing`) y fijan `finished_at`.
* Las funciones reciben un `Engine` de SQLAlchemy: este módulo no lee `DATABASE_URL` ni conoce al pipeline
  (dependencia unidireccional: el script usa `services/`, nunca al revés). Solo usa SQL estándar y fechas
  calculadas en Python, así que funciona igual sobre Postgres (producción) y SQLite (tests unitarios).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

PENDING = "pending"
PROCESSING = "processing"
COMPLETED = "completed"
FAILED = "failed"

MIGRATION_SQL = Path(__file__).resolve().parents[1] / "api" / "migrations" / "003_create_job_runs.sql"

# Un mensaje de error largo (p. ej. un traceback) no debe romper la transición a `failed`.
MAX_ERROR_LENGTH = 4000


@dataclass(frozen=True)
class JobRun:
    """Una fila de `job_runs`."""

    id: int
    job_name: str
    target_date: date
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    created_at: datetime | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_date(value: Any) -> date:
    """Acepta `date` o `YYYY-MM-DD`: SQLite (tests) devuelve fechas como texto, Postgres como `date`."""
    return value if isinstance(value, date) and not isinstance(value, datetime) else date.fromisoformat(str(value)[:10])


def _as_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _to_run(row: Any) -> JobRun:
    return JobRun(
        id=int(row["id"]),
        job_name=row["job_name"],
        target_date=_as_date(row["target_date"]),
        status=row["status"],
        started_at=_as_datetime(row["started_at"]),
        finished_at=_as_datetime(row["finished_at"]),
        error_message=row["error_message"],
        created_at=_as_datetime(row["created_at"]),
    )


def ensure_job_runs_table(engine: Engine) -> None:
    """Aplica `003_create_job_runs.sql` (idempotente, solo Postgres) para que el script funcione sin pasos manuales,
    igual que el pipeline hace con la migración 002. Puede ejecutarse a mano en Supabase → SQL Editor."""
    with engine.begin() as conn:
        conn.exec_driver_sql(MIGRATION_SQL.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Crear y consultar
# --------------------------------------------------------------------------- #
def create_job_run(engine: Engine, job_name: str, target_date: date) -> int:
    """Crea el registro en `pending` ANTES de empezar a trabajar y devuelve su `id`."""
    with engine.begin() as conn:
        return int(
            conn.execute(
                text("INSERT INTO job_runs (job_name, target_date, status, created_at) VALUES (:job, :day, 'pending', :now) RETURNING id"),
                {"job": job_name, "day": target_date, "now": _now()},
            ).scalar_one()
        )


def get_job_run(engine: Engine, run_id: int) -> JobRun | None:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM job_runs WHERE id = :id"), {"id": run_id}).mappings().first()
    return _to_run(row) if row else None


def has_processing_lock(engine: Engine, job_name: str) -> bool:
    """¿Hay otra ejecución de este job en `processing`? (esa fila ES el lock)."""
    with engine.connect() as conn:
        return conn.execute(text("SELECT 1 FROM job_runs WHERE job_name = :job AND status = 'processing' LIMIT 1"), {"job": job_name}).first() is not None


def has_completed_for_date(engine: Engine, job_name: str, target_date: date) -> bool:
    """Idempotencia por día: ¿ya hay un `completed` para `(job_name, target_date)`? Solo `job_name` no basta."""
    with engine.connect() as conn:
        return (
            conn.execute(
                text("SELECT 1 FROM job_runs WHERE job_name = :job AND target_date = :day AND status = 'completed' LIMIT 1"),
                {"job": job_name, "day": target_date},
            ).first()
            is not None
        )


# --------------------------------------------------------------------------- #
# Transiciones
# --------------------------------------------------------------------------- #
def mark_processing(engine: Engine, run_id: int) -> bool:
    """`pending → processing`: toma el lock. `True` si lo obtuvo; `False` si otra instancia ya está `processing`.

    La atomicidad la da la base de datos: el índice único parcial rechaza una segunda fila `processing` del mismo
    job aunque dos procesos lleguen en el mismo milisegundo. También devuelve `False` si el registro ya no estaba
    `pending` (p. ej. alguien lo marcó `failed` por obsoleto).
    """
    try:
        with engine.begin() as conn:
            updated = conn.execute(
                text("UPDATE job_runs SET status = 'processing', started_at = :now WHERE id = :id AND status = 'pending'"),
                {"id": run_id, "now": _now()},
            ).rowcount
        return updated == 1
    except IntegrityError:
        return False


def _finish(engine: Engine, run_id: int, status: str, error_message: str | None) -> bool:
    with engine.begin() as conn:
        updated = conn.execute(
            text(
                "UPDATE job_runs SET status = :status, finished_at = :now, error_message = :error "
                "WHERE id = :id AND status IN ('pending', 'processing')"
            ),
            {"id": run_id, "status": status, "now": _now(), "error": error_message},
        ).rowcount
    return updated == 1


def mark_completed(engine: Engine, run_id: int) -> bool:
    """`processing → completed`: solo si todo terminó bien. Libera el lock."""
    return _finish(engine, run_id, COMPLETED, None)


def mark_failed(engine: Engine, run_id: int, error_message: str) -> bool:
    """`→ failed` con el mensaje de la excepción. Libera el lock. No toca registros ya terminados."""
    return _finish(engine, run_id, FAILED, (error_message or "error sin mensaje")[:MAX_ERROR_LENGTH])


def delete_pending_run(engine: Engine, run_id: int) -> None:
    """Descarta un registro propio que se quedó en `pending` porque otra instancia ganó el lock (nunca llegó a trabajar)."""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM job_runs WHERE id = :id AND status = 'pending'"), {"id": run_id})


def fail_stale_runs(engine: Engine, job_name: str, max_age: timedelta) -> list[int]:
    """Recupera registros zombi: un proceso muerto sin pasar por `finally` (kill -9, corte del contenedor) deja la fila
    en `processing` (o `pending`) para siempre y bloquearía todas las noches siguientes. Si lleva más de `max_age`
    sin terminar, pasa a `failed` con un mensaje explicativo. Devuelve los `id` recuperados."""
    limit = _now() - max_age
    message = f"Registro obsoleto recuperado: seguía sin terminar tras {int(max_age.total_seconds() // 60)} min (proceso muerto o interrumpido)."
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, status, started_at, created_at FROM job_runs WHERE job_name = :job AND status IN ('pending', 'processing')"),
            {"job": job_name},
        ).mappings().all()
        stale = [int(r["id"]) for r in rows if (_as_datetime(r["started_at"] or r["created_at"]) or _now()) < limit]
        for run_id in stale:
            conn.execute(
                text("UPDATE job_runs SET status = 'failed', finished_at = :now, error_message = :msg WHERE id = :id AND status IN ('pending', 'processing')"),
                {"id": run_id, "now": _now(), "msg": message},
            )
    return stale
