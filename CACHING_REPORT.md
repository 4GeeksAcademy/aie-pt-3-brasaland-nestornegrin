# CACHING_REPORT.md — Optimización con caché, lazy loading y memoización

Rama: `feature/caching-optimisation`. Alcance: `services/api` (FastAPI) y `uis/backoffice` (Next.js 16 / React 19).

## Resumen

| Área | Qué se hizo | Resultado medido |
|---|---|---|
| Backend | Caché TTL (30 s) con invalidación en `GET /api/incidents/summary` y `GET /api/incidents` | resumen **71,7 → 2,4 ms** (mediana); listado **318,6 → 22,4 ms** |
| Frontend | Lazy loading de `SupplierDirectory` e `IncidentAnalysis` (carga al acercarse al viewport) | la llamada `/api/suppliers` (247 KB) ya no se hace al abrir la home |
| Frontend | `useMemo` + `useCallback` en las filas de la tabla de proveedores | **≈210 → ≈4,8 ms** por pulsación de tecla con 1 500 proveedores |

Todas las cifras son de un sandbox compartido (ruido de ±40 % entre ejecuciones); sirven para comparar el orden de magnitud, no como valores absolutos.

## Metodología y volumen de datos

- **Middleware de tiempos** en `services/api/app/main.py`: cada respuesta lleva la cabecera `X-Process-Time-Ms` y se registra una línea en el logger `api.timing` (`GET /ruta -> 200 | 12.3ms`).
- **Seeder reproducible** `services/api/seed_load.py` (semilla fija 42): genera datos variados y coherentes (países, categorías, sedes, estados, fechas) en un directorio de datos aparte.
  - Volumen **antes y después**: 1 500 proveedores y 8 000 incidencias (≈ 247 KB y ≈ 1,2 MB de JSON de respuesta). Es el mismo volumen en las dos mediciones; lo único que cambia es el código.
  - Volumen "de partida" del repositorio (sin seeder): decenas de registros, donde cualquier endpoint responde en pocos ms y la caché no aporta nada medible. Por eso hubo que cargar datos realistas.
- **Medidor** `services/api/measure_endpoints.py` (solo librería estándar): se registra, hace 40 peticiones por endpoint y muestra primera, mediana y p95.
- Los datos de prueba se sirven desde `BRASALAND_DATA_DIR`, de modo que ni el seeder ni los tests tocan los JSON de desarrollo (`services/api/app/database.py`; `tests/conftest.py` usa un directorio temporal).

Reproducir:

```bash
cd services/api
python seed_load.py --data-dir /tmp/brasaland-load --reset      # 1500 proveedores + 8000 incidencias
BRASALAND_DATA_DIR=/tmp/brasaland-load DATABASE_URL="sqlite:////tmp/test.db" \
  PYTHONPATH=../..:. uvicorn app.main:app --port 8772 &
python measure_endpoints.py --base http://localhost:8772 --label despues --requests 40
```

---

## Decisiones en el frontend

### Lazy loading (2 secciones)

Se cargan con `next/dynamic` desde un Client Component (`components/lazy-sections.tsx`). Es obligatorio que sea un Client Component: según la documentación de esta versión de Next, importar dinámicamente desde un Server Component no divide el código.

| Componente | Por qué es buen candidato |
|---|---|
| `SupplierDirectory` | Es lo más pesado de la home: al montarse pide `GET /api/suppliers` (247 KB con 1 500 proveedores) y pinta una tabla de 1 500 filas. Está por debajo del pliegue, así que el usuario no la ve al abrir la página. |
| `IncidentAnalysis` | Sección de análisis de CSV que solo se usa si el usuario sube un archivo; está al final de la página. |

Se envuelven en `DeferUntilVisible` (IntersectionObserver, margen de 300 px): el chunk **y** la petición de datos empiezan cuando la sección está cerca del viewport, no al cargar la página. El contenedor conserva `id="suppliers"` / `id="incidents"` antes de cargar, de modo que los enlaces del menú (`#suppliers`, `#incidents`) siguen funcionando. Verificado en Chromium contra el build de producción: al pulsar `#suppliers` se montan las 1 500 filas, al pulsar `#incidents` aparece el selector de CSV y no hay errores de consola.

Medición honesta (build de producción, Playwright):

| | Peticiones JS | JS transferido | Llamadas a la API al cargar |
|---|---|---|---|
| Antes | 12 | 557,2 KB | `/auth/me`, **`/api/suppliers`** |
| Después (al cargar) | 13 | 549,7 KB | `/auth/me` |
| Después (tras hacer scroll) | 15 | 561,9 KB | `/auth/me`, `/api/suppliers` (en ese momento) |

El JS inicial baja poco (≈ 1,3 %): los componentes son pequeños y comparten dependencias. **El beneficio real es retrasar la petición de 247 KB y el trabajo de renderizar 1 500 filas** hasta que el usuario llega a esa sección. Si nunca baja, nunca se paga. Con el dataset pequeño original el efecto sería imperceptible.

### `useMemo` (filas de la tabla de proveedores)

En `components/supplier-directory.tsx`, `tableRows = useMemo(() => suppliers.map(...), [suppliers, rates, saving, updateRate, updateStatus])`.

- **Por qué es no trivial:** con 1 500 proveedores, construir las filas (formato de fecha con `toLocaleString`, botones, inputs) cuesta ≈ 200 ms. Antes se rehacía en cada render, incluidos los renders provocados por escribir en el buscador o cambiar un filtro que no altera la lista.
- **Dependencias correctas:** `updateRate` y `updateStatus` se envuelven en `useCallback` (con `[rates]` y `[]`) porque, si fueran funciones nuevas en cada render, invalidarían el memo siempre y no serviría de nada.
- **Medido** (React Profiler `actualDuration`, jest/jsdom, 1 500 filas): **≈ 210 ms → ≈ 4,8 ms** por pulsación de tecla en un campo que no cambia la lista. Además hay un test determinista que cuenta las llamadas a `toLocaleString` (una por fila): no se repiten al re-renderizar sin cambiar las dependencias.
- jsdom con React en modo desarrollo es más lento que un navegador real: el valor absoluto es pesimista, la proporción es la que importa.
- **Qué no se memoizó:** los `useMemo` que ya existían en `backoffice-dashboard.tsx` operan sobre 5 registros de muestra. Es memoización prematura (el coste de comparar dependencias es comparable al cálculo); se dejan como están por no ampliar el alcance, pero no se añadieron más.

---

## Decisiones en el backend

### Análisis de endpoints

Criterios: (a) coste de la operación, (b) frecuencia de llamada, (c) frecuencia de cambio de los datos. Costes medidos con 1 500 proveedores / 8 000 incidencias, mediana de 40 peticiones, **antes** de cachear.

| Endpoint | (a) Coste | (b) Frecuencia | (c) Cambio de datos | ¿Cachear? |
|---|---|---|---|---|
| `GET /api/incidents/summary` | **Alto**: 71,7 ms, lee todo el archivo y agrega | **Alta**: panel de incidencias; se consulta al entrar y al refrescar | Baja (altas y cambios de estado puntuales) | **Sí** |
| `GET /api/incidents` (con y sin filtros) | **Alto**: 318,6 ms sin filtro (1,2 MB); 59 ms con `status=open` | **Alta**: pantalla principal de incidencias | Baja | **Sí** |
| `GET /api/suppliers` y `/{id}` | Bajo: 6–40 ms | Media | **Media**: las tarifas y estados se editan desde el propio backoffice | No |
| `POST/PUT/PATCH` de proveedores e incidencias | — (escrituras) | — | Invalidan la caché de incidencias | No (invalidan) |
| `GET /inventory/products` | Medio: **36,8 ms** (agrega ≈ 20 000 movimientos por ingrediente) | Media | **Alta**: cada entrada/salida cambia el stock | No (ver más abajo) |
| `GET /inventory/orders` | **Alto**: **503,6 ms** y 2,98 MB (20 000 movimientos) | Baja-media | **Alta**: crece con cada movimiento | No: se resuelve paginando, no cacheando (ver más abajo) |
| `GET /auth/me`, perfiles, usuarios | Muy bajo (2–3 ms) | Alta | — | No: datos **personales** |
| `POST /api/incidents/analyze`, exportación CSV | Medio | Baja | Dependen del archivo/consulta | No |

### Inventario (Postgres/Supabase), medido por separado

Se midió contra el proyecto de Supabase real (pooler `eu-west-1`, llamado desde un Codespace, así que el tiempo incluye la ida y vuelta a la base de datos) con `seed_inventory_load.py`: **300 ingredientes y 20 000 movimientos** (10 912 entradas y 9 088 salidas), 20 peticiones por endpoint:

| Endpoint | 1.ª petición | Mediana | p95 | Respuesta |
|---|---:|---:|---:|---:|
| `GET /inventory/products` | 62,2 ms | 36,8 ms | 62,2 ms | 32,0 KB |
| `GET /inventory/orders` | 698,5 ms | 503,6 ms | 577,4 ms | 2 980 KB |

En esa misma ejecución los endpoints de proveedores e incidencias respondieron en 1–5 ms porque el desarrollo solo tiene 10 proveedores y 90 incidencias; esas filas no sustituyen a las mediciones con volumen realista de arriba.

### `GET /api/incidents/summary`

- **Coste:** 71,7 ms de mediana (p95 193 ms) → recorre las 8 000 incidencias y agrega por categoría, estado y sede.
- **Frecuencia estimada de llamada:** una por cada visita al panel de incidencias, de varios usuarios; del orden de decenas por hora en un restaurante con backoffice abierto.
- **TTL elegido:** 30 s.
- **Invalidación:** `create_incident` y `update_incident_status` (solo si el estado cambia de verdad; un cambio sin efecto no invalida) vacían la caché.
- **Resultado:** mediana **71,7 → 2,4 ms**, p95 193,2 → 3,8 ms.

### `GET /api/incidents`

- **Coste:** 318,6 ms de mediana, 1,2 MB de respuesta. El profiling mostró que el tiempo no está en leer el archivo sino en **construir los modelos Pydantic**; por eso la caché guarda la tupla ya proyectada de `IncidentListItem` y no los registros crudos.
- **Frecuencia estimada:** misma pantalla que el resumen, más cada cambio de filtro. La clave de caché es `(status, origin, branch, category)`, así cada combinación de filtros se cachea por separado (máx. 64 entradas, con expulsión).
- **TTL:** 30 s. **Invalidación:** la misma que arriba (invalida todas las combinaciones).
- **Resultado:** `/api/incidents` **318,6 → 22,4 ms** (p95 393,8 → 38,7); `?status=open` **59,2 → 13,8 ms**. La primera petición tras una invalidación sigue costando como antes (257 ms): la caché ayuda a las siguientes.
- Cabecera `X-Cache: HIT|MISS` para poder comprobar el comportamiento desde fuera.

### Implementación (`services/api/app/cache.py`)

`TTLCache` propia, en memoria, con reloj inyectable (los tests avanzan el tiempo sin dormir):

- Expira por TTL y está acotada en tamaño (`max_entries`).
- **Invalidación segura ante carreras:** lleva un contador de versión. Si una lectura empieza, ocurre una escritura que invalida, y la lectura termina después, **no guarda** su valor (sería ya obsoleto). La función que calcula el valor se ejecuta fuera del cerrojo, así no se bloquean otras peticiones.
- 11 tests nuevos: expiración, invalidación, no almacenar tras escritura concurrente, expulsión, cabecera `X-Cache`, no-op de estado no invalida, y acceso sin sesión no sirve datos cacheados.

### Datos personales y claves compartidas

No se cachea nada con datos de sesión o personales (`/auth/me`, perfiles, usuarios). Los endpoints cacheados devuelven los **mismos datos a cualquier usuario autenticado** (incidencias del negocio, sin datos de cliente: el modelo no incluye nombre ni email del cliente), por lo que la clave contiene solo los filtros y no el usuario. La autenticación es una dependencia del router que se ejecuta **antes** del manejador: sin token válido se responde 401 sin llegar a la caché (cubierto con un test). Si en el futuro la respuesta dependiera del usuario (por ejemplo, "mis incidencias"), la clave tendría que incluir el id del usuario.

---

## Intercambios reconocidos

**Frescura vs. rendimiento — TTL de 30 s en incidencias.**

- Se eligió 30 s porque una incidencia (merma, queja, problema de proveedor) se gestiona en minutos u horas, no en segundos: que otro usuario vea una alta o un cambio de estado con hasta 30 s de retraso no cambia ninguna decisión. A cambio, el panel pasa de ≈ 320 a ≈ 22 ms.
- Los cambios hechos **desde la propia aplicación** no sufren ese retraso: la invalidación explícita en las escrituras hace que la siguiente lectura sea fresca. El frontend además actualiza de forma optimista la fila editada.
- **Límite conocido:** la caché es **por proceso**. Con varios workers de uvicorn, una escritura invalida solo la caché del worker que la atendió; los demás convergen por TTL (≤ 30 s). Lo mismo ocurre con escrituras externas a la API (por ejemplo, el script de seed): se verán como máximo 30 s tarde. Es aceptable aquí; si se escalara a varios workers y se exigiera consistencia inmediata, habría que pasar a Redis (o acortar el TTL).
- Un TTL mayor (5 min) daría más aciertos pero haría confusa la lista justo después de que un compañero cambie un estado; uno menor (5 s) casi no ahorraría con tráfico bajo.

**Lazy loading vs. salto de contenido:** el contenedor reserva una altura mínima (480/320 px) mientras la sección no ha cargado, para evitar saltos de layout; el coste es un hueco con el texto "Cargando…" si el usuario llega muy rápido.

---

## Qué no se cacheó y por qué

- **`GET /api/suppliers` (listado y detalle):** a 1 500 proveedores tarda 6–40 ms y el listado se edita desde el propio backoffice (tarifas, estado). El beneficio es pequeño y el riesgo de mostrar una tarifa antigua justo después de editarla es real. (Una opción más barata para el futuro es paginar, no cachear.)
- **`GET /inventory/orders` (503,6 ms, 2,98 MB):** es el endpoint más lento de toda la API y aun así no se cachea. El coste está en traer y serializar 20 000 filas (y en transferir 3 MB), no en un cálculo repetido: cachearlo ocultaría el síntoma y guardaría 3 MB en memoria por worker. Además es el historial de movimientos de stock, que crece con cada entrada y salida. La solución correcta es **paginarlo** (`limit`/`offset` o por sede/fecha), un cambio de contrato de la API que queda fuera de este ticket y se deja como siguiente paso.
- **`GET /inventory/products` (36,8 ms):** un coste moderado para un dato que cambia con cada movimiento y que se usa para decidir qué sacar de cocina. Con TTL el stock mostrado podría ir por detrás de la realidad.
- **Inventario (stock) y la validación de salidas:** la validación de una salida lee el stock **en vivo**; cachearlo permitiría aprobar salidas con existencias que ya no están. Aquí la frescura prevalece sobre el rendimiento.
- **`/auth/me`, perfiles y usuarios:** son datos personales y de sesión; cuestan 2–3 ms. No hay nada que ahorrar y sí riesgo de filtración entre usuarios.
- **`POST /api/incidents/analyze` y la exportación CSV:** dependen del archivo enviado o son de baja frecuencia.
- **Memoización en `backoffice-dashboard.tsx`:** 5 filas de muestra; coste del cálculo ≈ coste de comparar dependencias.

---

## Limitaciones y siguientes pasos

- Las cifras del backend son de un sandbox con ruido (±40 %); la mejora (≈ 3–30×) es mucho mayor que el ruido, pero los valores exactos variarán.
- Las cifras de `useMemo` vienen de jsdom en modo desarrollo: absolutas pesimistas, proporción fiable. Se pueden contrastar con el React DevTools Profiler (pestaña *Profiler* → grabar una pulsación de tecla en el buscador) y con la pestaña *Network* (ver que `/api/suppliers` aparece solo al hacer scroll).
- Pendiente de mejora (inventario): paginar `GET /inventory/orders` (3 MB con 20 000 movimientos).
- Pendiente de mejora: escribir en un campo de tarifa de una fila sigue renderizando todas las filas, porque el estado `rates` vive en el padre. Solución: un componente `SupplierRow` con estado local + `React.memo`.
- `GET /api/incidents` devuelve 1,2 MB con 8 000 incidencias; la mejora estructural es **paginarlo**, que reduciría tanto el coste de construir modelos como el tamaño transferido.
- Ejecutar los benchmarks del frontend: `cd uis/backoffice && BENCH=1 npx jest supplier-directory`.
