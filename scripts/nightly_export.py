#!/usr/bin/env python3
"""Script nocturno de telemetría (DEV-53): exporta el día anterior a CSV, lanza el pipeline y deja constancia en BD.

    python scripts/nightly_export.py                      # ayer (UTC)
    TARGET_DATE=2026-10-14 python scripts/nightly_export.py   # un día concreto, sin tocar el código

Qué hace, en orden (cada paso deja rastro en `public.job_runs`, ver `services/job_runner/`):

1. Resuelve `target_date`: variable `TARGET_DATE` (YYYY-MM-DD) o, por defecto, ayer en UTC.
2. Idempotencia por día: si ya hay un `completed` para `('nightly_export', target_date)`, se omite (no re-exporta
   el CSV ni relanza el pipeline) y se deja en el log.
3. Lock: el estado `processing` ES el lock (sin tabla, columna ni flag aparte). Si otra instancia está
   `processing`, esta aborta en silencio con código 0. La base de datos lo garantiza con un índice único parcial.
4. `pending → processing`, exporta `telemetry_events` del día a `data/raw/telemetry_YYYY-MM-DD.csv` SOLO si el
   archivo no existe (escritura atómica), y lanza el pipeline como subproceso.
5. `completed` si todo fue bien; ante CUALQUIER excepción `failed` + mensaje. El bloque `finally` garantiza que
   ningún registro quede en `processing`.

El CSV es un respaldo/auditoría: el pipeline NO lo lee, consume `telemetry_events` desde la base de datos.
El script es un proceso independiente: no importa ni ejecuta nada de FastAPI.

Códigos de salida: 0 = completado u omitido (duplicado/bloqueado) · 1 = falló · 2 = configuración inválida.
Variables opcionales: `TARGET_DATE`, `NIGHTLY_PIPELINE_TIMEOUT_SECONDS` (3600), `NIGHTLY_STALE_MINUTES` (120),
`NIGHTLY_PIPELINE_CMD` (sustituye el comando del pipeline; pensado para pruebas), `NIGHTLY_EXPORT_DIR`.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import shlex
import signal
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # misma técnica que services/api/app/main.py: la raíz del monorepo en sys.path
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

from services import job_runner  # noqa: E402

JOB_NAME = "nightly_export"
EXPORT_DIR = Path(os.environ.get("NIGHTLY_EXPORT_DIR", REPO_ROOT / "data" / "raw"))
CSV_COLUMNS = ["id", "event_id", "event_type", "timestamp", "service", "user_id", "session_id", "tags"]
PIPELINE_TIMEOUT_SECONDS = int(os.environ.get("NIGHTLY_PIPELINE_TIMEOUT_SECONDS", "3600"))
STALE_AFTER = timedelta(minutes=int(os.environ.get("NIGHTLY_STALE_MINUTES", "120")))  # siempre > timeout del pipeline

EXIT_OK, EXIT_FAILED, EXIT_BAD_CONFIG = 0, 1, 2


# --------------------------------------------------------------------------- #
# Logs: cada línea lleva timestamp, nombre del job y estado resultante
# --------------------------------------------------------------------------- #
class _UtcFormatter(logging.Formatter):
    converter = staticmethod(lambda *args: datetime.now(timezone.utc).timetuple())

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: N802
        return datetime.fromtimestamp(record.created, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _StdoutHandler(logging.StreamHandler):
    """Escribe en el `sys.stdout` ACTUAL (no el de la importación): cron lo redirige a archivo y los tests lo capturan."""

    def __init__(self) -> None:
        super().__init__(sys.stdout)

    @property
    def stream(self):  # type: ignore[override]
        return sys.stdout

    @stream.setter
    def stream(self, value) -> None:  # StreamHandler.__init__ lo asigna; se ignora a propósito
        pass


def _build_logger() -> logging.Logger:
    logger = logging.getLogger(JOB_NAME)
    if not logger.handlers:
        handler = _StdoutHandler()
        handler.setFormatter(_UtcFormatter("%(asctime)s | %(levelname)s | job=%(job)s | status=%(status)s | %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


_logger = _build_logger()


def log(level: int, status: str, message: str) -> None:
    """INFO para eventos normales (inicio, fin, omisión por duplicado) y ERROR para excepciones."""
    _logger.log(level, message, extra={"job": JOB_NAME, "status": status})


# --------------------------------------------------------------------------- #
# Fecha objetivo y CSV
# --------------------------------------------------------------------------- #
def resolve_target_date(env: dict[str, str] | None = None, today: date | None = None) -> date:
    """`TARGET_DATE` (YYYY-MM-DD) o, por defecto, AYER en UTC (`now(utc).date() - 1 día`)."""
    raw = (env if env is not None else os.environ).get("TARGET_DATE", "").strip()
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError as error:
            raise ValueError(f"TARGET_DATE='{raw}' no es una fecha válida (formato YYYY-MM-DD)") from error
    return (today or datetime.now(timezone.utc).date()) - timedelta(days=1)


def csv_path_for(target_date: date) -> Path:
    return EXPORT_DIR / f"telemetry_{target_date.isoformat()}.csv"


def export_telemetry_csv(engine: Engine, target_date: date) -> tuple[Path, int | None]:
    """Exporta `telemetry_events` de `target_date` (UTC) a `data/raw/telemetry_YYYY-MM-DD.csv`.

    Solo si el archivo no existe (devuelve `(ruta, None)` si ya estaba). Se escribe a un temporal y se renombra, así un
    corte a mitad nunca deja un CSV parcial que la siguiente ejecución dé por bueno. Un día sin eventos produce un
    CSV solo con la cabecera (queda constancia de que se exportó).
    """
    path = csv_path_for(target_date)
    if path.exists():
        return path, None
    path.parent.mkdir(parents=True, exist_ok=True)
    start = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
    tmp = path.with_suffix(".csv.tmp")
    rows = 0
    try:
        with engine.connect().execution_options(stream_results=True) as conn, tmp.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(CSV_COLUMNS)
            result = conn.execute(
                text(
                    'SELECT id, event_id, event_type, "timestamp", service, user_id, session_id, tags '
                    'FROM telemetry_events WHERE "timestamp" >= :start AND "timestamp" < :end ORDER BY id'
                ),
                {"start": start, "end": start + timedelta(days=1)},
            )
            for row in result:
                tags = row.tags if isinstance(row.tags, str) else json.dumps(row.tags, ensure_ascii=False, sort_keys=True)
                timestamp = row.timestamp.astimezone(timezone.utc).isoformat() if isinstance(row.timestamp, datetime) else row.timestamp  # siempre en UTC
                writer.writerow([row.id, row.event_id, row.event_type, timestamp, row.service, row.user_id, row.session_id, tags])
                rows += 1
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return path, rows


def pipeline_command(target_date: date) -> list[str]:
    """Comando del subproceso del pipeline: nuestro entry point (Hito 6) recalcula exactamente el día objetivo."""
    override = os.environ.get("NIGHTLY_PIPELINE_CMD")
    if override:
        return shlex.split(override)
    day = target_date.isoformat()
    return [sys.executable, "-m", "data.pipelines.pipeline", "--date-from", day, "--date-to", day, "--trigger", "cron"]


def failure_reason(stderr: str | None, stdout: str | None = None) -> str:
    """Motivo legible del fallo del subproceso para `job_runs.error_message`.

    La CLI del pipeline imprime `El pipeline falló: <causa>` y después Prefect añade líneas de apagado («Stopping
    temporary server…»): la ÚLTIMA línea no sirve. Se prefiere esa línea explícita; si no está (p. ej. un
    `ImportError` antes de arrancar), se usan las últimas líneas con contenido.
    """
    lines = [line.strip() for line in f"{stderr or ''}\n{stdout or ''}".splitlines() if line.strip()]
    explicit = [line for line in lines if line.startswith("El pipeline falló:")]
    if explicit:
        return explicit[-1].removeprefix("El pipeline falló:").strip()
    return " ⏎ ".join(lines[-3:]) if lines else "sin salida"


def run_pipeline(target_date: date) -> None:
    """Lanza el pipeline como subproceso (proceso aparte, sin hilos compartidos). Lanza si termina con error o por tiempo."""
    command = pipeline_command(target_date)
    log(logging.INFO, "processing", f"Lanzando pipeline: {shlex.join(command)}")
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=PIPELINE_TIMEOUT_SECONDS)
    if completed.returncode != 0:
        raise RuntimeError(f"El pipeline terminó con código {completed.returncode}: {failure_reason(completed.stderr, completed.stdout)}")
    log(logging.INFO, "processing", "Pipeline terminó correctamente")


# --------------------------------------------------------------------------- #
# Orquestación con la máquina de estados
# --------------------------------------------------------------------------- #
class _Terminated(Exception):
    """SIGTERM (p. ej. `docker stop`, systemd): se convierte en excepción para que `finally` cierre el registro."""


def _on_sigterm(signum, frame):  # noqa: ANN001
    raise _Terminated("El proceso recibió SIGTERM")


def run(engine: Engine, target_date: date) -> int:
    """Una ejecución completa para `target_date`. Devuelve el código de salida (ver docstring del módulo)."""
    # 1) Idempotencia por día: ya hecho → no se repite nada.
    if job_runner.has_completed_for_date(engine, JOB_NAME, target_date):
        log(logging.INFO, "completed", f"Omitido por duplicado: ya existe una ejecución completed para target_date={target_date}")
        return EXIT_OK

    # 2) Un proceso muerto a mitad deja su fila en `processing` y bloquearía todas las noches: se recupera.
    for stale_id in job_runner.fail_stale_runs(engine, JOB_NAME, STALE_AFTER):
        log(logging.ERROR, "failed", f"Registro obsoleto id={stale_id} recuperado a failed (llevaba más de {STALE_AFTER} sin terminar)")

    # 3) Lock: otra instancia `processing` → abortar en silencio.
    if job_runner.has_processing_lock(engine, JOB_NAME):
        log(logging.INFO, "processing", "Cancelado: otra instancia está en processing (lock). No se hace nada")
        return EXIT_OK

    # 4) pending → processing. Si otra instancia gana la carrera, el índice único parcial nos deja fuera.
    run_id = job_runner.create_job_run(engine, JOB_NAME, target_date)
    if not job_runner.mark_processing(engine, run_id):
        job_runner.delete_pending_run(engine, run_id)
        log(logging.INFO, "processing", "Cancelado: otra instancia tomó el lock justo antes. No se hace nada")
        return EXIT_OK

    previous_sigterm = signal.signal(signal.SIGTERM, _on_sigterm)
    exit_code = EXIT_FAILED
    try:
        log(logging.INFO, "processing", f"Inicio run_id={run_id} target_date={target_date}")
        path, rows = export_telemetry_csv(engine, target_date)
        if rows is None:
            log(logging.INFO, "processing", f"CSV ya existía, no se re-exporta: {path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path}")
        else:
            log(logging.INFO, "processing", f"CSV exportado: {path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path} ({rows} eventos)")
        run_pipeline(target_date)
        if not job_runner.mark_completed(engine, run_id):
            raise RuntimeError("No se pudo marcar completed: el registro ya no estaba en processing (¿recuperado como obsoleto?)")
        log(logging.INFO, "completed", f"Fin run_id={run_id} target_date={target_date}")
        exit_code = EXIT_OK
    except BaseException as error:  # noqa: BLE001 — incluye KeyboardInterrupt/SIGTERM: nada puede quedar en processing
        message = f"{type(error).__name__}: {error}"
        job_runner.mark_failed(engine, run_id, message)
        log(logging.ERROR, "failed", f"run_id={run_id} target_date={target_date} — {message}")
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        # Red de seguridad: si algo escapó incluso del bloque anterior, el registro no se queda en processing.
        current = job_runner.get_job_run(engine, run_id)
        if current is not None and current.status in (job_runner.PENDING, job_runner.PROCESSING):
            job_runner.mark_failed(engine, run_id, "La ejecución terminó sin cerrar el registro")
            log(logging.ERROR, "failed", f"run_id={run_id} cerrado por la red de seguridad")
    return exit_code


def main() -> int:
    try:
        target_date = resolve_target_date()
    except ValueError as error:
        log(logging.ERROR, "failed", str(error))
        return EXIT_BAD_CONFIG
    try:
        from data.pipelines.inventory_performance.db import get_engine  # lee DATABASE_URL (la misma que la API)

        engine = get_engine()
        job_runner.ensure_job_runs_table(engine)
    except Exception as error:  # noqa: BLE001 — sin BD no hay dónde dejar constancia: se avisa y se sale con error
        log(logging.ERROR, "failed", f"No se pudo preparar la conexión/tabla job_runs: {type(error).__name__}: {error}")
        return EXIT_BAD_CONFIG
    return run(engine, target_date)


if __name__ == "__main__":
    sys.exit(main())
