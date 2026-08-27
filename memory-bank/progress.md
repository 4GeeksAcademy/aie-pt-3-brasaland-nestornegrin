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
