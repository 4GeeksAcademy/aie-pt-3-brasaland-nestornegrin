"""Control de estado de los jobs nocturnos (`public.job_runs`) — DEV-53.

Reexporta la API pública de `services/job_runner/runner.py`. Se importa como `services.job_runner` con la raíz del
monorepo en `sys.path` (el script `scripts/nightly_export.py` y los tests lo hacen).
"""
from services.job_runner.runner import (  # noqa: F401
    COMPLETED,
    FAILED,
    MAX_ERROR_LENGTH,
    PENDING,
    PROCESSING,
    JobRun,
    create_job_run,
    delete_pending_run,
    ensure_job_runs_table,
    fail_stale_runs,
    get_job_run,
    has_completed_for_date,
    has_processing_lock,
    mark_completed,
    mark_failed,
    mark_processing,
)
