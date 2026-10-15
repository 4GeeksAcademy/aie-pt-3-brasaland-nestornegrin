-- DEV-53 · Registro de ejecuciones de jobs nocturnos (orquestación).
-- Ejecutar en Supabase → SQL Editor. Es idempotente (IF NOT EXISTS).
--
-- `job_runs` NO es `reporting.pipeline_runs`: son capas distintas.
--   · job_runs               → orquestación nocturna (scripts/nightly_export.py): export CSV, lanzamiento del
--                              subproceso del pipeline, lock e idempotencia del script. Esquema `public`.
--   · reporting.pipeline_runs → ETL interno del pipeline: fases, watermark, filas procesadas. Esquema `reporting`.
--
-- Máquina de estados:   pending → processing → completed
--                                           ↘ failed
-- El estado `processing` ES el lock distribuido (no hay otra tabla, columna o flag): el índice único parcial
-- `ux_job_runs_one_processing` hace que la base de datos garantice «una sola fila processing por job_name»
-- aunque dos procesos lo intenten a la vez (sin él, ambos podrían leer «no hay processing» y colarse los dos).

CREATE TABLE IF NOT EXISTS public.job_runs (
    id            BIGSERIAL PRIMARY KEY,
    job_name      TEXT        NOT NULL,                       -- p. ej. 'nightly_export'
    target_date   DATE        NOT NULL,                       -- día (UTC) que procesa la ejecución → idempotencia por día
    status        TEXT        NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    started_at    TIMESTAMPTZ,                                -- se fija al pasar a processing
    finished_at   TIMESTAMPTZ,                                -- se fija al pasar a completed | failed
    error_message TEXT,                                       -- mensaje de la excepción cuando status = 'failed'
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Consultas de idempotencia («¿hay un completed para este job y día?») y de lock.
CREATE INDEX IF NOT EXISTS ix_job_runs_job_name_target_date ON public.job_runs (job_name, target_date);

-- El lock: como máximo UNA fila `processing` por job_name.
CREATE UNIQUE INDEX IF NOT EXISTS ux_job_runs_one_processing
    ON public.job_runs (job_name) WHERE status = 'processing';

-- Mismo criterio que telemetry_events: Supabase expone `public` vía PostgREST; sin RLS cualquiera con la anon key
-- podría leer/escribir. La API y el script usan la conexión directa (rol postgres), que no se ve afectada.
ALTER TABLE public.job_runs ENABLE ROW LEVEL SECURITY;
