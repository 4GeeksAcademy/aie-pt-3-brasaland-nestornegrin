-- Tabla de almacenamiento de telemetría (feat: telemetry event storage).
-- Ejecutar en Supabase → SQL Editor. Es idempotente (IF NOT EXISTS).
-- Además, la API crea la tabla al arrancar (SQLModel.metadata.create_all) si no existe;
-- esta migración es la definición de referencia e incluye el trigger de inmutabilidad.

CREATE TABLE IF NOT EXISTS public.telemetry_events (
    id          BIGSERIAL PRIMARY KEY,
    event_id    UUID        NOT NULL UNIQUE,   -- eventId del envelope; evita duplicar reenvíos
    event_type  TEXT        NOT NULL,          -- entidad_acción (p. ej. outbound_order_created)
    "timestamp" TIMESTAMPTZ NOT NULL,          -- instante del suceso (reloj del emisor)
    service     TEXT        NOT NULL,          -- source: backend | frontend | job
    user_id     TEXT        NOT NULL,          -- userId (seudónimo; anonymous antes de login)
    session_id  TEXT        NOT NULL,          -- sessionId
    tags        JSONB       NOT NULL           -- properties (solo claves de la allowlist)
);

-- Índices que hacen la tabla consultable a escala.
CREATE INDEX IF NOT EXISTS ix_telemetry_events_timestamp  ON public.telemetry_events ("timestamp");
CREATE INDEX IF NOT EXISTS ix_telemetry_events_event_type ON public.telemetry_events (event_type);
CREATE INDEX IF NOT EXISTS ix_telemetry_events_tags       ON public.telemetry_events USING GIN (tags);

-- Los eventos son hechos inmutables: solo INSERT. Se bloquea UPDATE y DELETE también en la BD.
-- (Para limpiar datos de prueba usar TRUNCATE, que este trigger no intercepta.)
CREATE OR REPLACE FUNCTION public.telemetry_events_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'telemetry_events es de solo escritura (% no permitido)', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS telemetry_events_no_update_delete ON public.telemetry_events;
CREATE TRIGGER telemetry_events_no_update_delete
    BEFORE UPDATE OR DELETE ON public.telemetry_events
    FOR EACH ROW EXECUTE FUNCTION public.telemetry_events_immutable();

-- Supabase expone las tablas de `public` vía PostgREST: sin RLS cualquiera con la anon key
-- podría leer/escribir. La API usa la conexión directa (rol postgres), que no se ve afectada.
ALTER TABLE public.telemetry_events ENABLE ROW LEVEL SECURITY;
