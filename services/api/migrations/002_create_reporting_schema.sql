-- Esquema `reporting` del pipeline de desempeño de negocio (feat: implement resilient business performance pipeline).
-- Materializa el DDL de data/pipelines/PIPELINE_DESIGN.md §6 y §7.2.
--
-- Ejecutar en Supabase → SQL Editor, o dejar que el pipeline lo aplique solo en su primera corrida
-- (data/pipelines/inventory_performance/db.py::ensure_reporting_schema lee ESTE archivo).
-- Es idempotente: se puede ejecutar cuantas veces haga falta.
--
-- Principio de menor privilegio (diseño §8.3): el pipeline solo LEE `public.*` y solo ESCRIBE aquí.
-- Nada de este archivo toca `public.telemetry_events` ni `public.ingredient_*`.

CREATE SCHEMA IF NOT EXISTS reporting;

-- ---------------------------------------------------------------------------
-- Referencia: 14 restaurantes (CONTEXT.es.md) + el cubo de eventos sin restaurante identificable.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reporting.dim_restaurant (
    restaurant text PRIMARY KEY,
    country    text NOT NULL,
    city       text NOT NULL,
    timezone   text NOT NULL      -- zona IANA: define el «día local» de cada restaurante
);

INSERT INTO reporting.dim_restaurant (restaurant, country, city, timezone) VALUES
    ('Brasaland El Poblado',         'Colombia',       'Medellín', 'America/Bogota'),
    ('Brasaland Laureles',           'Colombia',       'Medellín', 'America/Bogota'),
    ('Brasaland Envigado',           'Colombia',       'Medellín', 'America/Bogota'),
    ('Brasaland Sabaneta',           'Colombia',       'Medellín', 'America/Bogota'),
    ('Brasaland Usaquén',            'Colombia',       'Bogotá',   'America/Bogota'),
    ('Brasaland Chapinero',          'Colombia',       'Bogotá',   'America/Bogota'),
    ('Brasaland Zona Rosa',          'Colombia',       'Bogotá',   'America/Bogota'),
    ('Brasaland Granada',            'Colombia',       'Cali',     'America/Bogota'),
    ('Brasaland Ciudad Jardín',      'Colombia',       'Cali',     'America/Bogota'),
    ('Brasaland Unicentro',          'Colombia',       'Cali',     'America/Bogota'),
    ('Brasaland Brickell',           'Estados Unidos', 'Miami',    'America/New_York'),
    ('Brasaland Coral Gables',       'Estados Unidos', 'Miami',    'America/New_York'),
    ('Brasaland Downtown',           'Estados Unidos', 'Orlando',  'America/New_York'),
    ('Brasaland International Drive','Estados Unidos', 'Orlando',  'America/New_York'),
    -- Cubo de calidad de dato (diseño §3.4): eventos cuyo `restaurant` falta o no es uno de los 14.
    ('UNATTRIBUTED',                 'N/A',            'N/A',      'UTC')
ON CONFLICT (restaurant) DO NOTHING;

-- ---------------------------------------------------------------------------
-- DESTINO DEL ENTREGABLE: 1 fila por (día local, restaurante). Los nombres de columna son los de los KPIs.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reporting.restaurant_inventory_daily (
    report_date                   date        NOT NULL,   -- día LOCAL del restaurante
    restaurant                    text        NOT NULL REFERENCES reporting.dim_restaurant (restaurant),
    outbound_orders               integer     NOT NULL,   -- K1
    units_issued                  numeric     NOT NULL,   -- K2
    spoilage_units                numeric     NOT NULL,
    spoilage_rate_pct             numeric,                -- K3 (NULL si units_issued = 0)
    stock_alerts_low              integer     NOT NULL,   -- K4
    stock_alerts_critical         integer     NOT NULL,
    validation_failures           integer     NOT NULL,
    validation_rejection_rate_pct numeric,                -- K5 (NULL si no hubo órdenes ni rechazos)
    ingredients_at_risk_eod       integer     NOT NULL,   -- K6 (stock al cierre <= 30)
    ingredients_critical_eod      integer     NOT NULL,   -- K6 (stock al cierre <= 10)
    telemetry_coverage_pct        numeric,                -- K1 ÷ salidas reales de ingredient_exits (NULL si no hubo salidas)
    events_deduplicated           integer     NOT NULL,
    capture_health                text        NOT NULL,   -- ok | real_zero | suspected_capture_gap
    source_max_event_id           bigint      NOT NULL,   -- tope de telemetry_events.id considerado en el cálculo
    kpi_hash                      text        NOT NULL,   -- huella de los valores: detecta si el recálculo cambió algo
    revision                      integer     NOT NULL DEFAULT 1,
    computed_at                   timestamptz NOT NULL,
    run_id                        uuid        NOT NULL,
    PRIMARY KEY (report_date, restaurant)                 -- el constraint único en el que se apoya el upsert
);

-- Histórico append-only: el valor ANTERIOR de un cubo ya publicado cuando un evento tardío lo corrige.
CREATE TABLE IF NOT EXISTS reporting.restaurant_inventory_daily_revisions (
    report_date                   date        NOT NULL,
    restaurant                    text        NOT NULL,
    outbound_orders               integer     NOT NULL,
    units_issued                  numeric     NOT NULL,
    spoilage_units                numeric     NOT NULL,
    spoilage_rate_pct             numeric,
    stock_alerts_low              integer     NOT NULL,
    stock_alerts_critical         integer     NOT NULL,
    validation_failures           integer     NOT NULL,
    validation_rejection_rate_pct numeric,
    ingredients_at_risk_eod       integer     NOT NULL,
    ingredients_critical_eod      integer     NOT NULL,
    telemetry_coverage_pct        numeric,
    events_deduplicated           integer     NOT NULL,
    capture_health                text        NOT NULL,
    source_max_event_id           bigint      NOT NULL,
    kpi_hash                      text        NOT NULL,
    revision                      integer     NOT NULL,
    computed_at                   timestamptz NOT NULL,
    run_id                        uuid        NOT NULL,
    superseded_at                 timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (report_date, restaurant, revision)
);

-- ---------------------------------------------------------------------------
-- Checkpoint: hasta qué telemetry_events.id llegó la última carga confirmada.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reporting.pipeline_watermarks (
    pipeline_name text   PRIMARY KEY,
    last_event_id bigint NOT NULL DEFAULT 0,
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Log de ejecución (diseño §7.2): 20 campos por corrida.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reporting.pipeline_runs (
    run_id              uuid        PRIMARY KEY,
    pipeline_name       text        NOT NULL,
    trigger             text        NOT NULL CHECK (trigger IN ('cron', 'manual', 'backfill')),
    triggered_by        integer,                               -- id de usuario (UserRecord) si fue manual
    started_at          timestamptz NOT NULL,
    finished_at         timestamptz,
    status              text        NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'skipped_locked', 'crashed')),
    watermark_from      bigint,
    watermark_to        bigint,
    rows_extracted      integer     NOT NULL DEFAULT 0,
    rows_deduplicated   integer     NOT NULL DEFAULT 0,
    rows_rejected       integer     NOT NULL DEFAULT 0,
    buckets_recomputed  integer     NOT NULL DEFAULT 0,
    rows_inserted       integer     NOT NULL DEFAULT 0,
    rows_updated        integer     NOT NULL DEFAULT 0,
    errors              jsonb       NOT NULL DEFAULT '[]'::jsonb,
    window_from         date,
    window_to           date,
    code_version        text        NOT NULL,
    prefect_flow_run_id uuid,
    heartbeat_at        timestamptz NOT NULL
);

-- Candado de exclusión mutua: como máximo UNA corrida `running` a la vez por pipeline.
-- Un segundo INSERT `running` viola este índice y se registra como `skipped_locked` (diseño §7.1 caso 3).
CREATE UNIQUE INDEX IF NOT EXISTS ux_pipeline_runs_one_running
    ON reporting.pipeline_runs (pipeline_name) WHERE status = 'running';
CREATE INDEX IF NOT EXISTS ix_pipeline_runs_started_at ON reporting.pipeline_runs (started_at DESC);

-- Supabase expone vía PostgREST solo los esquemas configurados; aun así se activa RLS por defensa en
-- profundidad. El pipeline y la API usan la conexión directa (rol postgres), que no se ve afectada.
ALTER TABLE reporting.dim_restaurant                       ENABLE ROW LEVEL SECURITY;
ALTER TABLE reporting.restaurant_inventory_daily           ENABLE ROW LEVEL SECURITY;
ALTER TABLE reporting.restaurant_inventory_daily_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reporting.pipeline_watermarks                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE reporting.pipeline_runs                        ENABLE ROW LEVEL SECURITY;
