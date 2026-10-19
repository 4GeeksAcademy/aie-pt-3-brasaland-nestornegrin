-- DEV-55 · Dead Letter Queue de la cola de tareas asíncronas (Celery).
-- El worker crea esta tabla solo la primera vez que una tarea agota sus reintentos; este fichero es el SQL
-- equivalente por si se prefiere crearla antes a mano en Supabase → SQL Editor. Es idempotente.
--
-- Una fila = una tarea que falló definitivamente (agotó max_retries):
--   task_id        id de Celery de la tarea (el mismo que devolvió POST /api/incidents/analyze)
--   attempt        nº de ejecución en la que se rindió (3 reintentos + el intento inicial = 4)
--   error_message  tipo y mensaje de la excepción
--   failed_at      momento del último fallo

CREATE TABLE IF NOT EXISTS public.task_dead_letters (
    id            BIGSERIAL PRIMARY KEY,
    task_id       TEXT        NOT NULL,
    task_name     TEXT        NOT NULL,
    attempt       INTEGER     NOT NULL,
    error_message TEXT        NOT NULL,
    failed_at     TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_task_dead_letters_task_id ON public.task_dead_letters (task_id);

-- Mismo criterio que el resto de tablas de `public`: Supabase expone este esquema vía PostgREST, y sin RLS
-- cualquiera con la anon key podría leer/escribir. El worker usa la conexión directa (rol postgres).
ALTER TABLE public.task_dead_letters ENABLE ROW LEVEL SECURITY;
