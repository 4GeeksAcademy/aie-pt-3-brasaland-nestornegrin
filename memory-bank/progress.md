# Progress — Brasaland monorepo

## Milestone 4 — Monorepo AI Setup

**Estado: completo, pendiente de verificación final del usuario y apertura de PR.**

### Infraestructura de agente (hecha)

- `memory-bank/projectbrief.md` y `memory-bank/techContext.md` creados con
  contexto real de negocio (Brasaland, stakeholders, Brasa Points) y técnico
  (stack, layout del monorepo, decisiones de arquitectura), no genérico.
- `AGENTS.md` raíz: qué leer al iniciar sesión, flujo de pre-commit de 5 pasos
  (releer progress.md → verificar local con typecheck/build/dev → actualizar
  progress.md → commit atómico → confirmar antes de tocar rutas protegidas),
  lista de rutas protegidas, y referencia a `.agents/rules/` y `.agents/skills/`.
- `.agents/rules/nextjs-app-boundaries.md` (alcance: siempre activa en `uis/`)
  y `.agents/rules/brasa-points-cascading-fields.md` (alcance: por patrón de
  archivo, cualquier archivo con los selects País/Ciudad/Ubicación).
- `.agents/skills/new-uis-app/SKILL.md`: skill para la tarea recurrente de
  scaffolding de una nueva app en `uis/`, con objetivo único, inputs
  documentados (`appName`, `audience`, `needsBusinessLogic`, `contextSource`)
  y criterios de aceptación verificables. Usada para crear tanto `website`
  como `backoffice` en este mismo hito.

### `uis/website` (hecho)

- Next.js 16.2.12 + React 19.2.4 + TypeScript + Tailwind v4, mismas versiones
  que `uis/talent-pipeline-tracker`.
- `/` migra el Hito 1 completo (`index.html`) a componentes React: header,
  hero, historia (con `next/image` en vez de `<img>`), valores, ubicaciones,
  teaser de Brasa Points, contacto y footer — mismo copy y estructura visual,
  implementación nueva.
- `/brasa-points` reemplaza `application.html`: formulario controlado con
  validación por campo en tiempo real, selects en cascada País→Ciudad→Ubicación
  (`lib/locations-data.ts`, con las 14 ubicaciones reales) y mensaje de éxito.
- El formulario reutiliza tipos y validaciones del Hito 2 (`../../../src/types/models`,
  `../../../src/validations`) — sin copiar el archivo fuente.
- `npm run build` y `npm run dev` verificados sin errores (`/` y `/brasa-points`
  responden 200).

### `uis/backoffice` (hecho)

- Mismo stack que `website`, layout propio e independiente.
- `/` muestra en pantalla (no solo en consola) la lógica del Hito 2: estadísticas
  agregadas de edad (`aggregateNumbers`), conteo por país/origen
  (`countRegistrationsByCountry`, `countRegistrationsBySource`), tabla filtrable
  y ordenable (`filterRegistrationsByCriteria`, `sortBy`), búsqueda por email
  (`linearSearch`) y por edad exacta (`binarySearch`), y validación de un
  registro de ejemplo con errores visibles (`validateRegistration`).
- Todo lo anterior se importa desde `../../../src/index`; `data/sample-registrations.ts`
  solo contiene datos de muestra (no lógica de negocio), por lo que sí vive
  dentro de la app.
- `npm run build` y `npm run dev` verificados sin errores.

### Verificado en esta sesión

- `grep` confirma imports reales hacia `src/` desde ambas apps y ninguna
  redefinición de las funciones de negocio dentro de `uis/` (solo aparecen en
  `.next/` como artefactos de build, ignorados por `.gitignore`).
- `.gitignore` de ambas apps excluye `.next/` y `node_modules/`.

### Pendiente (fuera del alcance evaluado de este hito, documentado para no perderlo)

- `CONTEXT.md` (versión en inglés) sigue siendo un placeholder genérico;
  `CONTEXT.es.md` sí tiene el contexto real y es la fuente usada para este hito.
- No hay autenticación ni backend real en `uis/backoffice` (decisión documentada
  en `techContext.md`, punto 3).
- La idea de un futuro agente de predicción de demanda/pedido de ingredientes
  (de `company-choice.md`) queda registrada en `projectbrief.md` como idea a
  futuro, no implementada en este hito.

## Milestone 5 — Análisis interno de incidencias

- Se añadió a `CONTEXT.es.md` el contrato exacto del CSV de postventa:
  `incident_id`, `customer_name`, `customer_email`, `category`, `status`,
  `created_at` y `satisfaction_score`, junto con categorías, estados y reglas
  de invalidez.
- `scripts/analyze.py` contiene la lógica reusable para lectura, validación,
  métricas, resumen de consola y exportación sin datos personales.
- `data/raw/incidents-COMPANY.csv` es una muestra sintética de 100 filas; sus
  expectativas verificadas son 90 válidas, 10 inválidas, 30 por categoría,
  estados 60/30/0 y media cerrada 3.00.
- `services/api` expone `POST /api/incidents/analyze` y
  `GET /api/incidents/results/export`; el último resultado se conserva en
  memoria durante el proceso para desarrollo local.
- `uis/backoffice` incorpora carga de CSV, resumen de análisis, causas de
  invalidez y descarga de resultados.
- Verificado: pruebas Python, fixture de 100 filas, smoke test HTTP, build de
  backoffice y `npm run typecheck` de la raíz.

## Milestone 6 — Directorio de proveedores

- `services/api/app/suppliers` añade modelos Pydantic, seeder, repositorio TinyDB y rutas CRUD para listar, crear, consultar, filtrar por país/categoría, actualizar tarifas/estado y eliminar.
- El seeder carga 10 proveedores de Brasaland al primer arranque; los estados son `Activo`/`Suspendido` y las categorías son `Carnes`, `Vegetales`, `Lácteos`, `Bebidas` y `Empaques`.
- `uis/backoffice` muestra el directorio conectado a la API, con filtros, formulario de alta, estados, timestamps y edición de tarifas.
- Verificado: smoke test FastAPI CRUD con seed, filtros, rechazo `422`, timestamp de tarifa, `uv run seed` dos veces sin duplicados y `npm run build` de backoffice.
- Nota: `CONTEXT-company.md` no existe en este checkout; el contrato de proveedores se definió a partir del encargo recibido.

## AUTH-01 — Autenticación y protección de rutas

- Se añadió CRUD de credenciales bajo `/users`, con roles `admin`, `manager` y
  `user`; las contraseñas se guardan únicamente como hashes bcrypt.
- Se añadieron `/auth/login`, `/auth/me`, `/profiles/me` y la dependencia
  reutilizable `get_current_user` para JWT stateless con expiración configurable.
- Usuarios y perfiles se almacenan en TinyDB separado (`users.json` y
  `profiles.json`); no se crean tablas de autenticación en SQL/Supabase.
- Se protegieron las rutas de incidencias y del directorio de proveedores.
- Verificado con smoke test: registro con perfil, login, hash de contraseña,
  401 sin token/token inválido, 403 sobre otro usuario y acceso autenticado a
  proveedores.

## AUTH-03 — Recuperación y cambio de contraseña

- `services/api`: `POST /auth/forgot-password` (siempre `200`, mismo mensaje
  exista o no el email), `POST /auth/reset-password` (`400` si el token es
  inválido, expiró o ya se usó) y `POST /auth/change-password` (autenticado,
  `400` si la contraseña actual no coincide).
- El token de restablecimiento es una cadena aleatoria (`secrets.token_urlsafe`),
  no un JWT: solo se guarda su hash SHA-256 en `password_resets.json` (TinyDB)
  junto con expiración y un flag `used`, porque un JWT con solo `exp` no puede
  invalidarse tras un único uso sin persistir estado en servidor de todas formas.
  Expiración configurable con `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES` (30 min
  por defecto).
- Envío de email con **Resend** (`app/auth/email.py`), variables
  `RESEND_API_KEY`, `EMAIL_FROM` y `FRONTEND_URL` (para construir el enlace
  `FRONTEND_URL/reset-password?token=...`); documentadas en `.env.example`.
  `.env` añadido a `services/api/.gitignore`.
- `uis/backoffice` incorpora `/forgot-password`, `/reset-password` (lee
  `token` del query string con `useSearchParams`, envuelto en `Suspense`) y
  `/account/change-password`. `/login` enlaza a `/forgot-password`; el menú
  de sesión enlaza a `/account/change-password`.
- Verificado: smoke test contra la app FastAPI real (`TestClient`, envío de
  email simulado) cubriendo los 12 criterios de la rúbrica — anti-enumeración,
  expiración, invalidación tras un solo uso, y los tres códigos `400`/`401`
  esperados —, además de `npm exec tsc --noEmit`, `npm run lint` y
  `npm run build` de `uis/backoffice` (las 3 páginas nuevas generan como
  contenido estático) sin errores.
- Pendiente para el desarrollador: probar el envío real con una `RESEND_API_KEY`
  propia (con el remitente `onboarding@resend.dev` solo se puede enviar a la
  dirección de la cuenta de Resend, sin dominio verificado) antes de abrir el PR.

## AUTH-02 — Flujos de autenticación en frontend

- `uis/backoffice` incorpora `/login`, `/register` y `/account/profile`.
- El cliente común guarda el JWT en `localStorage`, adjunta `Authorization:
  Bearer` a todas las llamadas protegidas y limpia/redirige ante `401`.
- El dashboard y el perfil usan un guard cliente; el logout elimina el token y
  redirige a `/login`. `uis/website` permanece completamente público.
- Registro, login, lectura de `/auth/me` y actualización de `/profiles/me` se
  integran contra la API existente; los errores `422` del registro se muestran
  por campo.
- Verificado: `npm exec tsc -- --noEmit`, `npm run lint`, `npm run build` y
  smoke test API con registro `201`, `401` sin token y `200` autenticado.

## Gestor de incidencias centralizado (extiende Hito 5)

- `services/api/app/incidents`: modelo `Incident` (`title`, `description`,
  `category`, `origin`, `branch`, `status`, `created_at`, `updated_at`) con
  ciclo de vida `open → in_progress → resolved`, y `discarded` alcanzable
  desde `open` o `in_progress`; `resolved`/`discarded` son finales. Las sedes
  (`branch`) son las 14 ubicaciones reales de `CONTEXT.es.md` (Hito 1) más
  `central`, ya que el CONTEXT no define un listado de sedes propio para
  incidencias.
- Endpoints: `POST/GET /api/incidents`, `GET /api/incidents/{id}`,
  `GET /api/incidents/summary` (totales por estado/categoría/origen/sede),
  `PATCH /api/incidents/{id}/status` (`400` con las transiciones válidas si
  la transición no está permitida; mismo estado = no-op `200`).
- Manejadores de error globales en `main.py`: `RequestValidationError` →
  `400` conservando el formato nativo de FastAPI (`detail`: lista de
  `{loc, msg}`) para no romper `readApiErrorDetails` ya existente en el
  frontend; `Exception` no controlada → `500` genérico sin stack trace.
- `scripts/seed_incidents.py`: carga `data/raw/incidents-COMPANY.csv` (el
  mismo del Hito 5) reutilizando `validate_incident_row` de
  `packages/shared/incident_validation.py` (nuevo — única fuente de verdad
  para los campos/categorías/estados válidos del CSV histórico, usada
  también por `scripts/analyze.py` y por `IncidentCategory` en la API, sin
  duplicar la lista en tres sitios). Mapea `origin: "customer"` y
  `branch: "central"` para todo el histórico (el CSV no tiene columna de
  sede), título `"Incidencia histórica {incident_id}"` (usado también como
  clave de idempotencia), estados `Abierto→open / Cerrado→resolved /
  Descartado→discarded`. No copia `customer_name`/`customer_email` (no
  forman parte del modelo y son datos personales). Verificado: 90
  insertadas/10 inválidas en la primera corrida (coincide con el Hito 5), 0
  insertadas/90 ya existían en la segunda; `/api/incidents/summary` tras el
  seed coincide exactamente con `incidents-file-analyzer`: total 90,
  por categoría 30/30/30, por estado (open/resolved/discarded) 60/30/0.
- `uis/backoffice`: `/incidents` (resumen agregado + panel con filtros por
  estado/origen/sede y cambio de estado en línea, con reversión visual si la
  actualización falla) y `/incidents/new` (formulario con el campo sede
  siempre visible y resaltado cuando el origen es "Sede"); enlace nuevo en el
  menú ("Gestor de incidencias"), sin tocar el enlace `#incidents` existente
  del análisis CSV del Hito 5.
- Se resolvió `react-hooks/set-state-in-effect` (regla nueva de
  `eslint-plugin-react-hooks@7`) difiriendo las llamadas a `setState` dentro
  de efectos a un microtask.
- Verificado: smoke test contra la API real (26/26 checks: filtros, las 5
  transiciones de estado límite, `404`/`401`/`400`/`500` genérico, resumen
  con las 15 sedes) y `tsc --noEmit` + `npm run lint` + `npm run build` del
  frontend sin errores (las 2 páginas nuevas generan como contenido
  estático).

## Auditoría de rendimiento de frontends

- Se ejecutó Lighthouse 13.5.0 sobre builds de producción de `uis/website` y
  `uis/backoffice`, en escritorio y móvil, incluyendo `/`, `/brasa-points`,
  `/login` y el dashboard autenticado. Los informes HTML/JSON y capturas están
  en `audit/before/` y `audit/after/` (con una captura `*-lighthouse.png` por informe).
- `uis/website/components/our-story-section.tsx` prioriza la imagen que
  Lighthouse identificó como LCP (`loading="eager"`, `fetchPriority="high"`).
- `uis/backoffice/app/page.tsx` difiere `SupplierDirectory` e
  `IncidentAnalysis` con `next/dynamic` para no incluir módulos secundarios en
  la carga inicial.
- Se extrajo `uis/backoffice/components/stat-card.tsx` y se integró en el
  dashboard y el análisis CSV, eliminando markup duplicado.
- Se corrigieron actualizaciones síncronas de estado en
  `inventory-outbound-form.tsx`; `npm run lint` y `npm run build` pasan en ambas
  apps (website conserva un warning preexistente de ESLint).
- `AUDIT.md` y `REPORT.md` documentan las métricas antes/después, causas raíz,
  impacto y limitaciones del laboratorio. La mejora principal del website fue
  Performance móvil `92→94` en home y `99→100` en Brasa Points; Best Practices
  del dashboard autenticado pasó `96→100` al medir con el origen local válido.
- Seguimiento de accesibilidad (2026-10-21): los dos `<select>` del formulario
  «Añadir proveedor» (`supplier-directory.tsx`) no tenían nombre accesible
  (`select-name`, Accessibility 96). Se añadió un `aria-label` a cada uno y el
  dashboard autenticado mide Accessibility `100` en escritorio y móvil
  (build + start de producción; control sin el arreglo reproduce el 96).


## Modelo de predicción de ventas (regresión)

- `scripts/sales_forecast/` (carga y validación, split, features causales, métricas, modelo, gráfica) y el CLI
  `scripts/train_sales_forecast.py`. Dataset provisto `data/raw/brasaland_sales.csv` (120 meses consolidados),
  sin modificar; su huella SHA-256 queda en `data/eval/sales_forecast/metrics.json`.
- Split temporal 8 años (2016-01 → 2023-12) / 2 años (2024-01 → 2025-12). El modelo predice la razón
  ventas/nivel de los 12 meses previos (para poder extrapolar el crecimiento) y se convierte a USD.
- Algoritmo elegido con validación walk-forward dentro del entrenamiento: Random Forest (XGBoost mejora el RMSE solo
  un 2,3 %, bajo el 5 % exigido, así que gana el modelo más simple). Semilla `random_state=42`.
- Resultados sobre la prueba (pronóstico recursivo de 24 meses): MSE 583.655.557 USD², error medio 2,72 %,
  Gini 0,908, K2 Score (R²) 0,893; PSI de ventas en bruto 5,65 (tendencia de crecimiento), PSI sin tendencia 0,23
  (dentro del ruido). Referencia "mismo mes del año pasado": 4,78 %. Explicación en
  `scripts/sales_forecast/README.es.md`.
- Descomposición en tendencia, estacionalidad y residuo (STL robusto sobre logaritmos, solo con los 96 meses de
  entrenamiento; añadido tras el comentario del revisor del PR #23): tendencia +5,7 % anual, estacionalidad con fuerza
  0,90 (enero −14 %, diciembre +19 %), residuo 2,4 %. Módulo `scripts/sales_forecast/decomposition.py`, salidas
  `decomposition.csv/png` y bloque `decomposition` en `metrics.json`; dependencia nueva `statsmodels` (con `uv add`).
  Las métricas del modelo no cambian.
- Pruebas en `tests/pipelines/` (19): `test_sales_split.py` (14: split 8/2, sin fuga de datos, escalador y semilla) y
  `test_sales_decomposition.py` (5: los componentes reconstruyen la serie, recuperan una estructura conocida y no usan
  meses de prueba). Se ejecutan con `uv run pytest tests/pipelines -v`.
- Nota: "K2 Score" no está definido en el ticket; se interpreta como R².

## Evaluación técnica del modelo de regresión (ticket "Evaluación de un Modelo de Regresión")

- Rama `feature/regression-model-eval` (sale de `feature/sales-forecast-model`: el PR #23 seguía abierto). Script
  `scripts/evaluate_sales_model.py` y módulo `scripts/sales_forecast/evaluation.py`; usa solo los 96 meses de
  entrenamiento, el conjunto de prueba no interviene.
- Validación cruzada: `TimeSeriesSplit(n_splits=5, test_size=12)` (entrena 24 a 72 meses, valida 2019-2023), con
  `verify_folds` (comprobación explícita de que nada se baraja ni se solapa) y features construidas con la serie
  recortada al final de cada fold. Métricas como media ± desviación estándar (ddof=1): MAE de validación 4,12 ± 1,11 %,
  RMSE 4,99 ± 1,71 %; entrenamiento 2,49 ± 0,65 % de MAE. Se añadió `mae` a `metrics.py`.
- Curva de aprendizaje en `data/eval/learning_curve.png` (validación fija = último año de entrenamiento). Reporte en
  `data/eval/evaluation_report.md` y cifras en `data/eval/evaluation_metrics.json`.
- Diagnóstico con una regla fijada antes de ver los números (contra el ruido irreducible de la descomposición, 1,88 %):
  **bien ajustado**, brecha de 1,5 puntos que regularizar más empeora (4,12 % → 5,14-5,58 %). Métrica principal: RMSE
  (el briefing pide MSE y no cuantifica si sobreestimar o subestimar cuesta más). Causa del error que sobra: sesgo
  cíclico ligado al crecimiento anual alterno (correlación −0,99 con 5 folds); una feature de crecimiento interanual no
  mejora (4,12 % → 4,64 %), así que no se incorpora. Acción: aprobar sin cambiar el modelo, entregar rango y vigilar el
  sesgo (umbral 2 %), reentrenar cada año.
- Pruebas: `tests/pipelines/test_cv_chronology.py` (13 con las parametrizadas): orden cronológico de los folds (la del
  ticket), rechazo de folds barajados o solapados, features sin fuga entre folds, resumen media ± desviación, curva de
  aprendizaje y diagnóstico. En total 32 pruebas en `tests/pipelines/`. No hay CI configurado en el repo (sin
  `.github/workflows`): se ejecutan con `uv run pytest tests/pipelines -v`.


## Plan de telemetría (diseño, sin código)

- `docs/telemetry/telemetry-plan.md` y `docs/telemetry/event-schemas.json` (JSON Schema draft-07): 31 eventos (7 obligatorios + 24 oportunidades identificadas) en 7 categorías, Event Envelope común, allowlist por evento, registro de datos sensibles, estrategia stream/batch (4 stream, 27 batch), riesgos y exclusiones, y guía de implementación.
- El `CONTEXT.es.md` del repo no define métricas de telemetría; se tomaron como obligatorias las siete preguntas del mensaje del tech lead (órdenes de salida/día, errores de validación por producto, intentos de editar stock, alertas de stock mínimo, logins fallidos, secciones más visitadas, flujos abandonados). Si el CONTEXT oficial trae otras, se añaden sin cambiar el envelope.
- Hallazgos del código registrados en el plan: el umbral de stock (10/30) solo existe en el frontend; no hay `X-Request-ID` ni sesión de servidor (JWT sin estado); el login no limita intentos; el registro es público; el alta de insumos no comprueba el rol.
- Verificado: el esquema valida como draft-07, cada evento tiene un ejemplo válido y casos inválidos rechazados (propiedad fuera de la allowlist, envelope incompleto, `source` incorrecto), y el plan y el JSON salen de la misma fuente.


## Captura de eventos de telemetría (`feat: telemetry event capture`)

- **Fase 1 (stub):** `POST /telemetry/events` en `services/api/app/telemetry/` (router propio). Acepta `{ "events": [...] }`, registra el nº de eventos y cada `event_type`, responde `{ "received": N }`. Modelo `TelemetryEvent` = envelope del plan. Lee el cuerpo en crudo (acepta `text/plain`) para que `sendBeacon` no necesite preflight de CORS. `TELEMETRY_ENDPOINT` declarada en `.env.example` (aún sin uso).
- **Fase 2 (servicio):** `uis/backoffice/services/telemetry.ts` con `track(eventType, properties)`: cola en memoria, lotes cada 10 s o 20 eventos, `sendBeacon` en `visibilitychange`/`pagehide`, 3 reintentos con backoff exponencial y descarte, campos estándar automáticos y validación contra la allowlist (`telemetry-schema.ts` se genera con `python3 scripts/gen-telemetry-schema.py`). URL en `NEXT_PUBLIC_TELEMETRY_ENDPOINT` (`.env.local`, no versionado).
- **Fase 3 (instrumentación):** ver la descripción del PR. Esquema revisado a 1.1.0 (11 eventos admiten `source: frontend`; `login_failed` con motivos del cliente).
- Verificado: 47 tests de la API, 55 de jest (incluye contrato con `ajv` contra `event-schemas.json`), `tsc`, `npm run build` y prueba real con Chromium: 7 lotes, todos `200`.
- Pendiente/limitaciones: `direct_stock_edit_rejected` no tiene ruta en la UI; `supplier_rate_updated`, `inbound_order_created`, `password_reset_*`, `incident_results_exported` y las vistas de secciones diferidas de la home no se capturan en el cliente.


## Almacenamiento de telemetría (`feat: telemetry event storage`)

- **Tabla** `telemetry_events` en Supabase (`services/api/migrations/001_create_telemetry_events.sql`): 8 columnas (`id`, `event_id` UNIQUE, `event_type`, `timestamp`, `service`, `user_id`, `session_id`, `tags` JSONB), índices en `timestamp`, `event_type` y GIN en `tags`, trigger que bloquea UPDATE/DELETE y RLS activado. La API también la crea al arrancar (`create_all`); la migración es la definición de referencia.
- **Endpoint real** `POST /telemetry/events` (reemplaza el stub; mismo envelope y misma URL, el frontend no cambió): body laxo, `TelemetryEvent.model_validate` por evento, rechazo individual (envelope inválido, `event_type` fuera del plan, faltan propiedades obligatorias), `tags` filtrado por la allowlist (`allowlists.py` se genera con `python -m app.telemetry.generate_allowlists`), una sola sentencia INSERT multi-VALUES con `ON CONFLICT (event_id) DO NOTHING`, respuesta `{received, stored, rejected}`.
- Decisión: `requestId` y `schemaVersion` se validan pero no se guardan (el ticket fija 8 columnas); un `eventId` repetido cuenta como `rejected`.
- Verificado con Postgres real: migración idempotente, índices, trigger, `tags @>` y E2E con el backoffice sin cambios (eventos técnicos y de negocio en la tabla).


## Reporte técnico de telemetría (`feat: telemetry report endpoint`)

- **Pipeline de análisis** `services/api/app/telemetry/analysis.py` (Pandas): 5 funciones de métrica independientes y sin efectos secundarios — `events_per_day`, `event_type_distribution`, `error_rate_by_type`, `latency_by_day`, `auth_failure_rate`. Fórmula fija: cargar (SQL con rango `[start, end)` y `event_type`) → refinar (campos de `tags`, flags `is_error`/`is_failure`) → `pd.to_datetime(utc=True)` → `groupby` → `agg`; sin bucles (un test lo comprueba con `ast`); cada una devuelve una lista de dicts serializable.
- **Endpoint** `GET /telemetry/report` (`report.py` + `routes.py`): requiere autenticación (la ingesta `POST /telemetry/events` sigue pública); `start_date`/`end_date` ISO 8601 opcionales, por defecto los últimos 7 días en UTC (máx. 90, 400 si es vacío o invertido); resuelve el período una vez y lo pasa a todas las métricas; devuelve `{period, metrics}`; caché en memoria con TTL de 60 s por combinación de fechas (cabecera `X-Cache: HIT|MISS`; las peticiones sin parámetros comparten clave).
- **Actividades adicionales hechas:** `auth_failure_rate` (con nuestros eventos `login_failed`/`login_succeeded`) y dashboard técnico `/telemetry` en `uis/backoffice` (tablas y barras CSS, muestra el `period`, ventanas 7 d/24 h/30 d).
- **Decisiones:** `analysis.py` vive en el módulo existente `services/api/app/telemetry/` (no hay carpeta `services/telemetry/`); errores técnicos = `frontend_error_captured`, `network_request_failed`, `api_unhandled_error_raised`, `request_validation_failed` (los rechazos de reglas de negocio no cuentan); la latencia viene de `api_latency_recorded`, que el frontend muestrea (5 % de las rápidas), así que `samples` no es volumen real. Dependencia nueva: `pandas` (`requirements.txt`, `pyproject.toml`, `uv.lock`).
- Verificado: 73 tests de la API (18 nuevos; también contra Postgres real), 55 de jest, `tsc`, build, y prueba en navegador con una réplica local de las 46 filas reales. Límite: hoy solo el frontend emite eventos, así que `api_unhandled_error_raised` y `request_validation_failed` (backend) no aparecen todavía.

## Pipeline de desempeño de negocio (`feat: add business performance pipeline design document`)

- **Solo diseño, sin código de orquestación:** `data/pipelines/PIPELINE_DESIGN.md` (Estado actual y brecha, propósito, extracción, diagrama E-T-L, actualizaciones/upsert, tablas destino, idempotencia, log de ejecución, mapeo a Prefect, 3 endpoints en `services/reporting/`, respuestas a las 10 preguntas de diseño).
- **Entregable de negocio:** consolidado diario «Desempeño de Inventario por Restaurante» (`reporting.restaurant_inventory_daily`, PK `(report_date, restaurant)`) con K1–K6 sobre `outbound_order_created`, `stock_threshold_triggered` e `inventory_validation_failed`. `telemetry_events` es solo fuente; no se toca `analysis.py` ni `GET /telemetry/report`; v1 no añade campos al payload.
- **Pendiente de validar (⚑ en el documento):** el repo no tiene `CONTEXT-company.md` de data pipelines (sin «KPIs a medir» ni «Destination table»); KPIs, nombre de tabla y frecuencia se derivaron de `CONTEXT.es.md` (Hito 6), `company-choice.md` y el plan de telemetría. Hoy solo el frontend emite eventos; el backend aún no.


## Pipeline resiliente de desempeño de negocio (`feat: implement resilient business performance pipeline`)

- **Implementa el diseño** de `data/pipelines/PIPELINE_DESIGN.md` con Prefect 3: `data/pipelines/pipeline.py` (flow `inventory_performance_daily_flow` + backfill; tasks extract → transform → load; `python data/pipelines/pipeline.py [--date-from --date-to --serve]`). Transformaciones puras en `data/process/business_kpis.py`; acceso a datos en `data/pipelines/inventory_performance/`.
- **Resiliencia:** `retries`/`retry_delay_seconds` justificados por task; fallos manejados con `return_state=True` (`PipelineStageError`, `finish_run` siempre se ejecuta); task opcional `export_eval_snapshot`; caché de `transform_daily_kpis` con `cache_key_fn` + `cache_expiration` (1 h).
- **Idempotencia:** upsert `ON CONFLICT (report_date, restaurant)` con `kpi_hash`, revisiones append-only y checkpoint por `telemetry_events.id` (solape 2000) en la misma transacción; candado por índice único parcial en `pipeline_runs`; filas `running` sin heartbeat → `crashed`.
- **Tablas** (`services/api/migrations/002_create_reporting_schema.sql`, esquema `reporting`): `restaurant_inventory_daily`, `…_revisions`, `dim_restaurant`, `pipeline_watermarks`, `pipeline_runs`. `telemetry_events` solo se lee.
- **Endpoints** `services/reporting/` (autenticados): `GET /reporting/inventory-performance/status`, `POST …/runs` (202/409/400), `GET …/kpis`. Importan de `data/pipelines/`; nunca al revés.
- **Decisiones/limitaciones:** no existe `CONTEXT-company.md` (se usan las propuestas ⚑); `analysis.py` real en `services/api/app/telemetry/` (intacto); el disparo manual solo exige autenticación; Dockerfile debe copiar `data/` y `services/reporting/`.
- Verificado: suite por defecto (104 passed, 15 skipped) y 15 tests de integración contra Postgres real; dos ejecuciones seguidas (2.ª: transform en caché, 0 insertadas, 43 sin cambios).

## Auditoría de serialización de la API

- Auditados todos los endpoints de `services/api` (33 lógicos); el detalle por endpoint, con su estado inicial y final, está en `docs/serialization-audit.md`. Ningún endpoint devolvía un objeto ORM ni `hashed_password`; los problemas eran esquemas de salida heredados del de entrada, claves de almacenamiento expuestas, el email repetido en el registro y `/api/incidents/analyze` devolviendo un `dict` sin tipar.
- Nuevos esquemas de salida: `ProfilePublic`, `RegisterResponse`, `UserListItem` (auth), `SupplierResponse`, `IncidentResponse`, `IncidentListItem` y `AnalysisResponse`. `OrderResponse.type` pasa a `Literal["inbound", "outbound"]`.
- `POST /users` ya no devuelve el email (solo `id` y `message`); `is_active` en `PUT /users/{id}` pasa a requerir admin; `POST /auth/login` exige `email` o `username`.
- `user_uuid` en las órdenes de inventario se conserva a propósito: la tabla del backoffice lo muestra.
- `response_model=None` explícito en los dos borrados 204 y en la descarga CSV (las únicas operaciones sin cuerpo JSON), fijado con un test.
- Verificado: 54 tests (42 existentes + 12 de contrato en `tests/test_serialization.py`; 7 de los nuevos fallan contra el código anterior) y prueba manual con `uvicorn` y `curl`. El frontend no necesitó cambios.


## Optimización con caché, lazy loading y memoización

- Informe completo con cifras antes/después en `CACHING_REPORT.md`.
- Backend: middleware de tiempos (`X-Process-Time-Ms` + logger `api.timing`), `app/cache.py` (`TTLCache` en memoria con TTL, tamaño acotado e invalidación segura ante carreras) y caché de 30 s en `GET /api/incidents` y `GET /api/incidents/summary`, invalidada al crear incidencias y al cambiar su estado. Con 1 500 proveedores y 8 000 incidencias (`seed_load.py`): resumen 71,7 → 2,4 ms, listado 318,6 → 22,4 ms. No se cachean proveedores, inventario ni datos de sesión. Inventario medido en Supabase con 300 ingredientes y 20 000 movimientos: `/inventory/products` 36,8 ms y `/inventory/orders` 503,6 ms y 2,98 MB (se resuelve paginando, no cacheando).
- `BRASALAND_DATA_DIR` permite apuntar los JSON de TinyDB a otro directorio; los tests usan uno temporal y ya no ensucian los datos de desarrollo.
- Frontend (`uis/backoffice`): `SupplierDirectory` e `IncidentAnalysis` se cargan con `next/dynamic` al acercarse al viewport (`DeferUntilVisible`, conserva las anclas `#suppliers`/`#incidents`); `useMemo` + `useCallback` en las filas de proveedores (≈210 → ≈4,8 ms por pulsación con 1 500 filas).
- Verificado: 65 tests de backend, jest (15 + 1 benchmark opcional), anclas y consola en Chromium contra el build de producción.
