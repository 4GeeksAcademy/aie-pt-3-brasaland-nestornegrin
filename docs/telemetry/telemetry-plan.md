# Plan de Telemetría — Brasaland

| | |
|---|---|
| **Versión del plan / de los esquemas** | 1.1.0 |
| **Estado** | Propuesta para revisión (viernes). No hay código de instrumentación en este PR. |
| **Entregables** | Este documento y [`event-schemas.json`](./event-schemas.json) (JSON Schema draft-07, validado contra este plan) |
| **Alcance** | `services/api` (FastAPI + TinyDB + Supabase), `uis/backoffice` (Next.js) y tareas programadas |

## 0. Resumen

El sistema de inventario funciona, pero nadie puede responder preguntas operativas sobre él ni sobre el resto del backoffice. Este plan define **qué se captura, con qué forma, quién lo emite, cada cuánto se procesa y qué nunca se captura**, con el detalle suficiente para que otra persona lo implemente sin hacer preguntas.

- **31 eventos** diseñados: **7 obligatorios** (las preguntas que el tech lead pidió medir «sí o sí») y **24 oportunidades identificadas** por mí a partir del código real.
- **7 categorías** cubiertas: negocio (inventario, incidencias, proveedores), autenticación, rendimiento, errores y navegación/flujos.
- **Entrega:** 4 eventos en *stream* (≤ 60 s) y 27 en *batch* (6 con corte «cada hora», 21 con corte «diario»). La decisión se justifica siempre por la urgencia de la decisión que alimenta (sección 7).
- **Privacidad por defecto:** cada evento tiene una allowlist cerrada de propiedades (`additionalProperties: false`); ningún texto libre, email, IP, mensaje de error ni valor de formulario se captura (sección 6).

| Categoría | Obligatorios | Identificados | Total |
|---|--:|--:|--:|
| Negocio · inventario | 4 | 4 | 8 |
| Negocio · incidencias | 0 | 5 | 5 |
| Negocio · proveedores | 0 | 1 | 1 |
| Autenticación | 1 | 6 | 7 |
| Rendimiento | 0 | 2 | 2 |
| Errores | 0 | 4 | 4 |
| Navegación y flujos | 2 | 2 | 4 |
| **Total** | **7** | **24** | **31** |

**Cómo leer el documento:** §1 explica de dónde salen las métricas obligatorias y qué hallazgos del código condicionan el diseño; §2 mapea el flujo de inventario; §3 define el *Event Envelope*; §4 es el catálogo; §5 la especificación evento por evento; §6–§8 privacidad, entrega y riesgos; §9 la guía de implementación; §10 la trazabilidad con los criterios de evaluación.

## 1. Fuentes, supuestos y hallazgos

### 1.1 Origen de las métricas obligatorias

El enunciado indica que el `CONTEXT` de la empresa contiene una lista de métricas obligatorias. **El `CONTEXT.es.md` de este repositorio no incluye ninguna sección de métricas ni de telemetría** (solo cubre el Hito 1, el Hito 5 y el Hito 6 de inventario) y no existe otro archivo de contexto en el repo. Para no inventar «métricas del CONTEXT», se tratan como obligatorias **las siete preguntas que el tech lead enumera literalmente en su mensaje**, y así se marcan en el catálogo:

| Pregunta literal del tech lead | Evento obligatorio |
|---|---|
| «¿Cuántas órdenes de salida se registran por día?» | `outbound_order_created` |
| «¿Qué productos acumulan más errores de validación?» | `inventory_validation_failed` |
| «¿Hay usuarios intentando modificar el stock directamente y siendo rechazados?» | `direct_stock_edit_rejected` |
| «¿Cuándo se disparan más las alertas de stock mínimo?» | `stock_threshold_triggered` |
| «¿Cuántos intentos de login fallidos hay por día?» | `login_failed` |
| «¿Qué secciones visitan más los operadores?» | `navigation_section_viewed` |
| «¿Hay flujos que se abandonan a la mitad?» | `flow_abandoned` |

> **Si el `CONTEXT` oficial trae métricas distintas o adicionales**, se incorporan como eventos obligatorios nuevos sin tocar el envelope ni los demás esquemas (ver reglas de versionado en §3.3).

### 1.2 Entidades y reglas de negocio del sistema de inventario (CONTEXT, Hito 6)

| Regla del CONTEXT | Implicación para la telemetría |
|---|---|
| Entidades `Ingredient` (producto, con `restaurant`), `IngredientEntry` (orden de entrada) e `IngredientExit` (orden de salida). | Los eventos usan `ingredientId`, `restaurant` y los ids de orden como únicos identificadores de negocio; nunca nombres ni SKU. |
| `current_stock` = Σ entradas − Σ salidas; **nunca** se edita directamente. | Todo intento de fijarlo directamente es una señal de integridad: `direct_stock_edit_rejected`. Cada evento de orden lleva `stockBefore`/`stockAfter` calculados, no leídos de una columna. |
| Las órdenes guardan el `user_uuid` (entero) del usuario autenticado. | `userId` del envelope es ese mismo entero como texto; permite cruzar telemetría con las órdenes. |
| Una salida que dejaría el stock negativo se rechaza **antes** de persistirse (400). | `inventory_validation_failed` con `errorCode = insufficient_stock` y `availableStock`. |
| Todos los endpoints de inventario exigen autenticación. | Los eventos de inventario siempre llevan un `userId` real; los anónimos solo existen antes del login. |
| `restaurant` es la clave de partición: el stock es local a cada restaurante. | `restaurant` es una dimensión en todos los eventos de inventario (14 restaurantes en Colombia y Florida). |

### 1.3 Hallazgos del código que condicionan el diseño

Revisados en `services/api` y `uis/backoffice`; cada uno aparece en el evento al que afecta.

1. **El umbral de stock mínimo solo existe en el frontend** (`LOW_STOCK_THRESHOLD = 10`, `HEALTHY_STOCK_THRESHOLD = 30` en `lib/inventory.ts`): ni el backend ni el CONTEXT lo definen, y hoy solo colorea una tabla. `stock_threshold_triggered` exige moverlo a configuración del servidor (§5.4).
2. **No hay sesión de servidor ni identificador de petición.** La autenticación es un JWT sin estado (vigencia 30 min) y no existe `X-Request-ID`. `sessionId` y `requestId` se definen en §3.2.
3. **`POST /auth/login` no limita intentos** y no deja rastro de los fallidos.
4. **`POST /users` (registro) es público**: cualquiera puede crear una cuenta con acceso al backoffice (`user_registered`).
5. **`POST /inventory/products` solo exige estar autenticado**, no comprueba el rol y no guarda quién creó el insumo (`ingredient_created`).
6. **El campo `supplier` de las entradas es texto libre** sin enlace al directorio de proveedores (`inbound_order_created`).
7. **Los errores 500 devuelven un mensaje genérico** y el detalle queda solo en el log de uvicorn (`api_unhandled_error_raised`).
8. **Los errores de validación ya se unifican en un 400** (`RequestValidationError` → 400), y `IngredientCreate` usa `extra="forbid"`: por eso un intento de enviar `current_stock` se rechaza y es detectable en ese handler (`direct_stock_edit_rejected`).
9. **No hay `app/error.tsx` ni captura global de errores** en el backoffice, y no se mide ningún Web Vital (`frontend_error_captured`, `web_vital_measured`).
10. **La interfaz de salida ya bloquea el envío si la cantidad supera el stock mostrado**, así que un `insufficient_stock` que llega al servidor indica una carrera (el stock cambió) o un cliente que no usa la interfaz.

### 1.4 Lo que este plan no hace

No escribe código de instrumentación, no elige un proveedor de analítica externo y no define paneles; define el contrato de datos y la estrategia de entrega.

## 2. Mapa del flujo de inventario y puntos de instrumentación

Flujo completo de un usuario autenticado, desde que abre el sistema hasta que completa una orden:

```text
Login ──► AuthGuard (GET /auth/me) ──► /inventory/products ──► elegir insumo ──► formulario de orden
  │              │                        (lista + niveles)         │              (entrada o salida)
  │              └─ 401 → session_expired                           │
  └─ 401 → login_failed                                             ▼
                                              GET /inventory/products/{id} (stock actual)
                                                                    │
                                              ¿cantidad > stock? ── sí ──► aviso en pantalla (envío bloqueado)
                                                                    │ no
                                                                    ▼
                                              POST /inventory/orders/{inbound|outbound}
                                                 ├─ 404 insumo / 400 stock / 400 cantidad ─► rechazo
                                                 └─ 201 ─► orden guardada ─► ¿cruzó un umbral? ─► alerta
```

| # | Punto de instrumentación | Qué ocurre ahí | Evento(s) |
|--:|---|---|---|
| IP1 | Entrada a la sección de inventario | El usuario llega a `/inventory/products` o a un formulario tras pasar `AuthGuard`. | `navigation_section_viewed` |
| IP2 | Lectura de la lista de insumos | `GET /inventory/products` agrega el stock de todos los movimientos. | `api_latency_recorded`; foto diaria: `stock_snapshot_recorded` |
| IP3 | Inicio de la orden | El usuario modifica el primer campo del formulario. | `flow_started` |
| IP4 | Aviso de cantidad excesiva | La cantidad escrita supera el stock mostrado, o se bloquea el envío por eso. | `outbound_overdraw_warning_shown` |
| IP5 | Rechazo del servidor | 404 insumo inexistente, 400 stock insuficiente o 400 cantidad inválida. | `inventory_validation_failed` |
| IP6 | Orden creada | Respuesta 201 y `commit()` en la base de datos. | `outbound_order_created` / `inbound_order_created`, `flow_completed` |
| IP7 | Cruce de umbral | Tras una salida, el stock baja de 30 (bajo) o de 10 (crítico). | `stock_threshold_triggered` |
| IP8 | Intento directo de modificar stock | `POST /inventory/products` con `current_stock`, o `PUT/PATCH/DELETE` sobre un insumo. | `direct_stock_edit_rejected` |
| IP9 | Salida sin terminar | El usuario abandona el formulario o caduca la sesión con datos sin enviar. | `flow_abandoned`, `session_expired` |
| IP10 | Fallo técnico | La red falla o el servidor lanza una excepción no controlada. | `network_request_failed`, `api_unhandled_error_raised` |
| IP11 | Alta de insumo | `POST /inventory/products` correcto. | `ingredient_created` |

Resto del backoffice (oportunidades fuera del inventario):

| Sección / flujo | Eventos |
|---|---|
| Login, registro y recuperación de contraseña | `login_succeeded`, `login_failed`, `user_registered`, `password_reset_requested`, `password_reset_completed`, `password_reset_failed`, `session_expired` |
| Incidencias (alta, lista, cambio de estado, análisis y exportación de CSV) | `incident_created`, `incident_status_changed`, `incident_list_filtered`, `incident_csv_analyzed`, `incident_results_exported` |
| Directorio de proveedores | `supplier_rate_updated` |
| Transversal (toda la aplicación) | `api_latency_recorded`, `web_vital_measured`, `frontend_error_captured`, `request_validation_failed`, `navigation_section_viewed`, `flow_started`, `flow_completed`, `flow_abandoned` |

## 3. Event Envelope

Todo evento, sin excepción, tiene exactamente esta estructura. `properties` es el único lugar para datos específicos del evento.

| Campo | Tipo | Obligatorio | Regla |
|---|---|:-:|---|
| `eventId` | texto | sí | Identificador único del evento (UUID v4 generado por el emisor). Sirve para deduplicar reenvíos. |
| `timestamp` | texto | sí | Instante en que ocurrió el suceso, ISO 8601 en UTC con milisegundos y sufijo Z (reloj del emisor). |
| `sessionId` | texto | sí | UUID v4 de la sesión de navegador (se genera al abrir la pestaña y se guarda en sessionStorage; viaja en la cabecera X-Session-Id). `system` en eventos de tareas programadas. |
| `userId` | texto | sí | `UserRecord.id` (entero) como texto; `anonymous` antes de autenticarse; `system` en tareas programadas; `deleted` en eventos históricos de un usuario que se dio de baja (se reescribe al borrar la cuenta). Es un identificador seudónimo. |
| `event_type` | texto | sí | Tipo de evento con taxonomía `entidad_acción`, en minúsculas y snake_case; la última palabra es un verbo de la lista cerrada. |
| `schemaVersion` | texto | sí | Versión semántica del esquema de este evento. |
| `requestId` | texto | sí | UUID v4 que une frontend, backend y logs. Lo genera el cliente por petición y viaja en X-Request-ID; si falta o no es un UUID, el middleware genera uno. Los eventos de tareas programadas usan un UUID por ejecución. |
| `source` | texto | sí | Componente que emite el evento. |
| `properties` | objeto | sí | Payload específico del evento; cada evento define su allowlist. |

### 3.1 Ejemplo

```json
{
  "eventId": "3f2b8c1e-5a47-4d9e-9b6a-1c7d2e4f8a90",
  "timestamp": "2026-10-07T16:20:31.245Z",
  "sessionId": "b71e0c52-8d3a-4f16-a2c9-6e5d4b3a2f10",
  "userId": "7",
  "event_type": "outbound_order_created",
  "schemaVersion": "1.1.0",
  "requestId": "9c4d7a3e-1b28-4e5f-8a6d-0f2e1c3b4a59",
  "source": "backend",
  "properties": {
    "exitId": 4812,
    "ingredientId": 17,
    "restaurant": "Brasaland El Poblado",
    "quantity": 12.5,
    "stockBefore": 31,
    "stockAfter": 18.5,
    "reasonProvided": true
  }
}
```

### 3.2 Cómo se generan y se propagan los identificadores

- **`eventId`:** UUID v4 generado por quien emite. Es la clave primaria del almacén: un reenvío (p. ej. `sendBeacon` repetido) no duplica el evento.
- **`sessionId`:** la API usa un JWT sin estado, así que **no existe una sesión de servidor**. Se define como un UUID v4 que genera el frontend al abrir la pestaña (se guarda en `sessionStorage`) y envía en la cabecera `X-Session-Id` en cada petición vía `apiFetch`. El backend copia esa cabecera; si falta o no es un UUID (cliente que usa la API directamente), genera un UUID nuevo por petición. Las tareas programadas usan el literal `system`.
- **`userId`:** el `sub` del JWT (el `UserRecord.id` entero, como texto). `anonymous` antes de autenticarse (incluido `login_failed`: una identificación fallida no es una sesión). `system` en tareas programadas. `deleted` sustituye al id cuando se da de baja al usuario (ver §6.3).
- **`requestId`:** une frontend, backend y logs. `apiFetch` genera un UUID v4 por llamada y lo envía en `X-Request-ID`; el middleware HTTP lo valida (si falta o no es un UUID, genera uno), lo devuelve en la cabecera de respuesta y lo añade a la línea de log de la petición (el logger `api.timing` del PR #12 de caché, si ya está fusionado). Los eventos del servidor emitidos durante esa petición lo reutilizan. Un evento de frontend asociado a una llamada (`network_request_failed`, `session_expired`) reutiliza el de esa llamada; los demás (p. ej. `navigation_section_viewed`) generan uno nuevo.
- **`timestamp`:** instante del suceso, UTC con milisegundos (`2026-10-07T16:20:31.245Z`). Los eventos del frontend usan el reloj del cliente, que puede estar desfasado: el almacén guarda además `received_at` (columna aparte, **no** forma parte del envelope) y se marca como sospechoso cualquier evento con más de 5 minutos de diferencia.
- **`source`:** `backend`, `frontend` o `job`. Es obligatorio; es fijo por evento salvo en los 11 eventos que, desde la versión 1.1.0, también emite el frontend (ver «Revisión 1.1.0»); permite saber qué lado perdió datos si un embudo no cuadra.

### 3.3 Taxonomía y versionado

- **`event_type` = `entidad_acción`**, en minúsculas y snake_case; la **última palabra es un verbo en participio** de esta lista cerrada: `created`, `rejected`, `triggered`, `failed`, `succeeded`, `completed`, `expired`, `viewed`, `started`, `abandoned`, `recorded`, `measured`, `captured`, `raised`, `changed`, `analyzed`, `filtered`, `shown`, `registered`, `updated`, `requested`, `exported`. Un verbo nuevo requiere modificar este documento. Se nombran hechos ya ocurridos, nunca clics sueltos ni intenciones.
- **`schemaVersion`** (semver, por evento; hoy `1.1.0`): añadir una propiedad opcional = *minor*; añadir una obligatoria, quitar una, cambiar un tipo o ampliar/estrechar un enum de forma incompatible = *major* y se emiten ambas versiones durante la migración; cambiar solo descripciones = *patch*. Los consumidores deben ignorar versiones *minor* que no conozcan, pero no *major*.

## 4. Catálogo de eventos

| # | `event_type` | Categoría | Grupo | Emite | Entrega |
|--:|---|---|---|---|---|
| 1 | `outbound_order_created` | Negocio · inventario | obligatorio | backend + frontend | batch · cada hora |
| 2 | `inventory_validation_failed` | Negocio · inventario | obligatorio | backend + frontend | batch · diario |
| 3 | `direct_stock_edit_rejected` | Negocio · inventario | obligatorio | backend + frontend | stream · ≤ 60 s |
| 4 | `stock_threshold_triggered` | Negocio · inventario | obligatorio | backend + frontend | stream · ≤ 60 s |
| 5 | `login_failed` | Autenticación | obligatorio | backend + frontend | stream · ≤ 60 s |
| 6 | `navigation_section_viewed` | Navegación y flujos | obligatorio | frontend | batch · diario |
| 7 | `flow_abandoned` | Navegación y flujos | obligatorio | frontend | batch · diario |
| 8 | `inbound_order_created` | Negocio · inventario | oportunidad | backend | batch · diario |
| 9 | `ingredient_created` | Negocio · inventario | oportunidad | backend | batch · diario |
| 10 | `outbound_overdraw_warning_shown` | Negocio · inventario | oportunidad | frontend | batch · diario |
| 11 | `stock_snapshot_recorded` | Negocio · inventario | oportunidad | job | batch · diario |
| 12 | `incident_created` | Negocio · incidencias | oportunidad | backend + frontend | batch · diario |
| 13 | `incident_status_changed` | Negocio · incidencias | oportunidad | backend + frontend | batch · cada hora |
| 14 | `incident_csv_analyzed` | Negocio · incidencias | oportunidad | backend + frontend | batch · diario |
| 15 | `incident_list_filtered` | Negocio · incidencias | oportunidad | frontend | batch · diario |
| 16 | `incident_results_exported` | Negocio · incidencias | oportunidad | backend | batch · diario |
| 17 | `supplier_rate_updated` | Negocio · proveedores | oportunidad | backend | batch · diario |
| 18 | `login_succeeded` | Autenticación | oportunidad | backend + frontend | batch · diario |
| 19 | `session_expired` | Autenticación | oportunidad | frontend | batch · diario |
| 20 | `password_reset_requested` | Autenticación | oportunidad | backend + frontend | batch · cada hora |
| 21 | `password_reset_completed` | Autenticación | oportunidad | backend + frontend | batch · diario |
| 22 | `password_reset_failed` | Autenticación | oportunidad | backend + frontend | batch · diario |
| 23 | `user_registered` | Autenticación | oportunidad | backend + frontend | batch · cada hora |
| 24 | `api_latency_recorded` | Rendimiento | oportunidad | backend + frontend | batch · cada hora |
| 25 | `web_vital_measured` | Rendimiento | oportunidad | frontend | batch · diario |
| 26 | `api_unhandled_error_raised` | Errores | oportunidad | backend | stream · ≤ 60 s |
| 27 | `frontend_error_captured` | Errores | oportunidad | frontend | batch · cada hora |
| 28 | `network_request_failed` | Errores | oportunidad | frontend | batch · diario |
| 29 | `request_validation_failed` | Errores | oportunidad | backend | batch · diario |
| 30 | `flow_started` | Navegación y flujos | oportunidad | frontend | batch · diario |
| 31 | `flow_completed` | Navegación y flujos | oportunidad | frontend | batch · diario |

## 5. Especificación de cada evento

Cada evento cumple la regla de oro: *«Capturamos [`event_type`] porque necesitamos saber [hipótesis], lo que nos permite tomar la decisión [decisión concreta]»*. Las propiedades listadas son la **allowlist completa**: nada fuera de ellas se puede emitir. Los tipos y restricciones exactos están en `event-schemas.json`.

### 5.1 `outbound_order_created`

**Negocio · inventario** · **obligatorio** · emite: **backend + frontend** · entrega: **batch** (cada hora)

> Capturamos `outbound_order_created` porque necesitamos saber cuántas órdenes de salida se registran por día, restaurante e insumo, y si ese volumen refleja el consumo real de cocina o mermas, lo que nos permite tomar la decisión de ajustar los pedidos de reposición por restaurante y detectar días con consumo anómalo.

- **Situación actual:** Pregunta literal del tech lead («¿cuántas órdenes de salida se registran por día?»). Hoy solo se puede contar con una consulta manual a la base de datos.
- **Dónde se emite:** `services/api/app/inventory/routes.py` → `create_outbound_order`, justo después de `session.commit()`. `stockBefore` es el `current_stock` ya calculado para validar; `stockAfter = stockBefore − quantity`.
- **Entrega (batch, cada hora):** La pregunta de operaciones es «cuántas órdenes de salida por día»: una cifra diaria no cambia ninguna decisión en segundos; un corte horario alimenta el panel del turno sin coste de streaming.
- **Throttle / debounce:** Ninguno: una orden = un evento (baja frecuencia, se crea desde un formulario).
- **Datos sensibles:** Sin PII. `reason` (texto libre) **no** se captura: puede contener nombres o datos personales; solo `reasonProvided`.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `exitId` | entero | sí | `IngredientExit.id` de la orden creada. (≥ 1) |
| `ingredientId` | entero | sí | `Ingredient.id`. (≥ 1) |
| `restaurant` | texto | sí | `Ingredient.restaurant` (uno de los 14 restaurantes). (máx. 64 car.) |
| `quantity` | número | sí | Cantidad retirada (> 0). (> 0) |
| `stockBefore` | número | sí | Stock del insumo justo antes de la orden. (≥ 0) |
| `stockAfter` | número | sí | Stock tras la orden (≥ 0 por la regla de negocio). (≥ 0) |
| `reasonProvided` | booleano | sí | Si el usuario escribió un motivo (el texto no se emite). |

### 5.2 `inventory_validation_failed`

**Negocio · inventario** · **obligatorio** · emite: **backend + frontend** · entrega: **batch** (diario)

> Capturamos `inventory_validation_failed` porque necesitamos saber qué productos acumulan más errores de validación y si esos rechazos se concentran en pocos insumos, lo que nos permite tomar la decisión de dar un stock de seguridad mayor o corregir los datos maestros de esos insumos, y decidir si hay que bloquear antes en la interfaz.

- **Situación actual:** Pregunta literal del tech lead («¿qué productos acumulan más errores de validación?»). Hoy los rechazos devuelven 400/404 al cliente y no dejan rastro agregable.
- **Dónde se emite:** `inventory/routes.py` → ramas `404` de `create_inbound_order`/`create_outbound_order` y `400` de stock insuficiente; y el handler `RequestValidationError` de `main.py` cuando la ruta es `/inventory/orders/inbound` o `/inventory/orders/outbound` (`invalid_quantity` si el error es del campo `quantity`, `invalid_payload` en otro caso). Este evento **sustituye** a `request_validation_failed` en esas dos rutas (no se emiten los dos).
- **Entrega (batch, diario):** Se analiza como ranking semanal de insumos problemáticos; nadie actúa sobre un rechazo concreto en minutos.
- **Throttle / debounce:** Ninguno. Nota: la interfaz ya bloquea el envío si la cantidad supera el stock mostrado, así que un `insufficient_stock` que llega al servidor indica una carrera (el stock cambió después de leerlo) o un cliente que no usa la interfaz.
- **Datos sensibles:** Sin PII. El texto del error HTTP (`detail`) **no** se captura: incluye el nombre del insumo y del restaurante en texto libre.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `operation` | texto | sí | Operación rechazada. (valores: `inbound_order`, `outbound_order`) |
| `errorCode` | texto | sí | Causa normalizada. (valores: `insufficient_stock`, `ingredient_not_found`, `invalid_quantity`, `invalid_payload`) |
| `httpStatus` | entero | sí | Código HTTP devuelto. (valores: `400`, `404`) |
| `ingredientId` | entero | no | Insumo implicado; ausente si el cuerpo no trae un id válido. (≥ 1) |
| `restaurant` | texto | no | Restaurante del insumo, solo si el insumo existe. (máx. 64 car.) |
| `requestedQuantity` | número | no | Cantidad pedida, si es numérica. |
| `availableStock` | número | no | Stock disponible; solo con `insufficient_stock`. (≥ 0) |

### 5.3 `direct_stock_edit_rejected`

**Negocio · inventario** · **obligatorio** · emite: **backend + frontend** · entrega: **stream** (≤ 60 s)

> Capturamos `direct_stock_edit_rejected` porque necesitamos saber si hay usuarios o clientes que intentan fijar el stock directamente en lugar de usar órdenes de entrada y salida, y cuántas veces lo repiten, lo que nos permite tomar la decisión de dar formación, crear un flujo oficial de «ajuste de inventario» (con motivo y aprobación) o alertar de seguridad sobre esa cuenta.

- **Situación actual:** Pregunta literal del tech lead («¿hay usuarios intentando modificar el stock directamente y siendo rechazados?»). La regla del CONTEXT es que el stock solo cambia por órdenes trazables; hoy el rechazo (400 o 405) no se registra.
- **Dónde se emite:** Dos puntos: (a) handler `RequestValidationError` de `main.py`: ruta `/inventory/products`, error de tipo `extra_forbidden` cuyo campo sea `current_stock`, `stock` o `quantity` (`IngredientCreate` usa `extra="forbid"`); (b) nuevo handler de `StarletteHTTPException` para `405` en `/inventory/products` y `/inventory/products/{ingredient_id}` con método `PUT`, `PATCH` o `DELETE` (hoy esas rutas no existen y Starlette responde 405). Cualquier otro campo extra va a `request_validation_failed`.
- **Entrega (stream, ≤ 60 s):** Es una señal de integridad: intentar saltarse la regla «el stock solo cambia por órdenes» una vez es una duda; repetido en minutos desde la misma cuenta puede ser un error de integración o un uso indebido, y hay que poder avisar mientras ocurre.
- **Throttle / debounce:** Sin throttle (evento raro). El procesador de stream agrupa por `userId` y avisa a partir de 3 intentos en 10 minutos.
- **Datos sensibles:** Sin PII. Solo se guardan los **nombres** de los campos ofensivos (lista cerrada), nunca sus valores.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `attemptKind` | texto | sí | Cómo se intentó. (valores: `extra_field_on_create`, `unsupported_method`) |
| `httpMethod` | texto | sí | Método HTTP usado. (valores: `POST`, `PUT`, `PATCH`, `DELETE`) |
| `routeTemplate` | texto | sí | Plantilla de ruta (nunca la ruta con ids). (valores: `/inventory/products`, `/inventory/products/{ingredient_id}`) |
| `httpStatus` | entero | sí | Código devuelto. (valores: `400`, `405`) |
| `offendingFields` | lista | no | Campos de stock enviados (solo `attemptKind = extra_field_on_create`). (elementos: `current_stock`, `stock`, `quantity`) |
| `ingredientId` | entero | no | Insumo de la ruta, si el intento fue contra `/{ingredient_id}`. (≥ 1) |

### 5.4 `stock_threshold_triggered`

**Negocio · inventario** · **obligatorio** · emite: **backend + frontend** · entrega: **stream** (≤ 60 s)

> Capturamos `stock_threshold_triggered` porque necesitamos saber cuándo y dónde se disparan más las alertas de stock mínimo, y si la reposición llega tarde en ciertos restaurantes u horarios, lo que nos permite tomar la decisión de avisar de inmediato al encargado del restaurante para pedir reposición y, a medio plazo, redefinir umbrales y frecuencia de pedido por restaurante.

- **Situación actual:** Pregunta literal del tech lead («¿cuándo se disparan más las alertas de stock mínimo?»). Hoy el umbral (10 y 30) solo existe en el frontend, solo colorea una tabla y no genera ningún aviso ni registro.
- **Dónde se emite:** `create_outbound_order`, tras `commit()`: se emite cuando el stock **cruza hacia abajo** un umbral (`stockBefore > T` y `stockAfter ≤ T`). Umbrales: `T = 30` → `low`, `T = 10` → `critical` (los de `LOW_STOCK_THRESHOLD`/`HEALTHY_STOCK_THRESHOLD` de `uis/backoffice/lib/inventory.ts`, que hoy solo existen en el frontend). Si una orden cruza ambos, se emite solo `critical`. No se emite al leer ni al crear un insumo (nace con stock 0).
- **Entrega (stream, ≤ 60 s):** Un restaurante sin un ingrediente base para la brasa no puede servir: la reposición se pide en horas, así que el aviso al encargado debe llegar en menos de un minuto; un informe diario llegaría después de que se agote.
- **Throttle / debounce:** Disparo por **cruce** (edge-triggered), no por nivel: no se repite mientras el stock siga por debajo; solo se vuelve a emitir tras recuperarse por encima del umbral. Evita inundar el canal con cada lectura.
- **Datos sensibles:** Sin PII.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `ingredientId` | entero | sí | Insumo afectado. (≥ 1) |
| `restaurant` | texto | sí | Restaurante del insumo. (máx. 64 car.) |
| `level` | texto | sí | Umbral cruzado. (valores: `low`, `critical`) |
| `thresholdValue` | número | sí | Valor del umbral cruzado (30 o 10 en la v1). (valores: `30`, `10`) |
| `stockBefore` | número | sí | Stock antes de la orden. (≥ 0) |
| `stockAfter` | número | sí | Stock después de la orden. (≥ 0) |
| `triggeringExitId` | entero | sí | `IngredientExit.id` que provocó el cruce. (≥ 1) |

### 5.5 `login_failed`

**Autenticación** · **obligatorio** · emite: **backend + frontend** · entrega: **stream** (≤ 60 s)

> Capturamos `login_failed` porque necesitamos saber cuántos intentos de login fallidos hay por día y si son olvidos de contraseña (pocos intentos por cuenta) o ataques de relleno de credenciales (muchas cuentas desde un mismo origen), lo que nos permite tomar la decisión de activar un bloqueo temporal o limitación de intentos y reforzar el flujo de recuperación de contraseña.

- **Situación actual:** Pregunta literal del tech lead («¿cuántos intentos de login fallidos hay por día?»). Hoy `POST /auth/login` no limita intentos ni deja rastro de ellos.
- **Dónde se emite:** `services/api/app/auth/routes.py` → `login`, en la rama que lanza el `401`. Hoy el endpoint no limita intentos ni deja rastro de ellos.
- **Entrega (stream, ≤ 60 s):** Detectar relleno de credenciales requiere contar intentos por ventana de minutos; con un informe diario el ataque ya habría terminado.
- **Throttle / debounce:** Sin throttle: es baja frecuencia y cada intento cuenta. Si hubiera un ataque, el procesador agrega y el almacenamiento aplica el tope de volumen (ver sección 7).
- **Datos sensibles:** **Sí, seudonimizado.** Nunca se guarda el email ni la IP. `accountKey` = primeros 16 hex de HMAC-SHA256(email en minúsculas, clave secreta de telemetría); `sourceKey` = ídem sobre la IP con una clave que rota cada día (permite correlacionar dentro del día, no seguir a una persona entre días). `userId` es siempre `anonymous` (una identificación fallida no es una sesión).

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `failureReason` | texto | sí | Causa. Backend: `unknown_account`/`wrong_password` (nunca se devuelve al cliente). Frontend: `invalid_credentials` (401), `network_error` (sin respuesta), `server_error` (otro estado). (valores: `unknown_account`, `wrong_password`, `invalid_credentials`, `network_error`, `server_error`) |
| `accountKey` | texto | no | HMAC truncado del email intentado (16 hex). (formato validado por patrón) |
| `sourceKey` | texto | no | HMAC truncado de la IP, clave rotada a diario (16 hex). (formato validado por patrón) |

### 5.6 `navigation_section_viewed`

**Navegación y flujos** · **obligatorio** · emite: **frontend** · entrega: **batch** (diario)

> Capturamos `navigation_section_viewed` porque necesitamos saber qué secciones visitan más los operadores y cuáles casi no se usan, lo que nos permite tomar la decisión de priorizar qué secciones mejorar o simplificar y qué colocar primero en el menú.

- **Situación actual:** Pregunta literal del tech lead («¿qué secciones visitan más los operadores?»). Hoy no hay ninguna medición de uso del backoffice.
- **Dónde se emite:** Hook de cliente `useTrackSectionView(section)` en cada `app/**/page.tsx`, una vez la sesión está autorizada (tras `AuthGuard`). En la home, `suppliers` e `incident_analysis` emiten cuando la sección se hace visible: si el PR #12 (caché y carga diferida) está fusionado, desde el callback de visibilidad de `DeferUntilVisible`; si no, al montarse cada sección.
- **Entrega (batch, diario):** Es una pregunta de producto de largo plazo (qué secciones mantener): una agregación diaria basta.
- **Throttle / debounce:** Deduplicar: misma sección dentro de 30 s (re-render, cambio de hash, volver a la pestaña) no vuelve a emitir.
- **Datos sensibles:** Sin PII. Solo valores de una lista cerrada; nunca la URL completa ni la query string.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `section` | texto | sí | Sección vista. (valores: `dashboard`, `suppliers`, `incident_analysis`, `incidents_manager`, `incident_new`, `inventory_products`, `inventory_orders`, `inventory_inbound`, `inventory_outbound`, `account_profile`, `account_password`, `login`, `register`, `forgot_password`, `reset_password`) |
| `previousSection` | texto | no | Sección anterior en la sesión; ausente en la primera. (valores: `dashboard`, `suppliers`, `incident_analysis`, `incidents_manager`, `incident_new`, `inventory_products`, `inventory_orders`, `inventory_inbound`, `inventory_outbound`, `account_profile`, `account_password`, `login`, `register`, `forgot_password`, `reset_password`) |
| `entryKind` | texto | sí | Cómo se llegó. (valores: `menu_click`, `direct_url`, `redirect`, `anchor_link`, `scroll_into_view`) |

### 5.7 `flow_abandoned`

**Navegación y flujos** · **obligatorio** · emite: **frontend** · entrega: **batch** (diario)

> Capturamos `flow_abandoned` porque necesitamos saber qué flujos se abandonan a la mitad, en qué punto y por qué desencadenante, lo que nos permite tomar la decisión de simplificar el formulario que más abandona, adelantar validaciones y revisar si la caducidad de sesión (30 min) interrumpe trabajo a medias.

- **Situación actual:** Pregunta literal del tech lead («¿hay flujos que se abandonan a la mitad?»). Hoy un formulario a medias que se descarta es invisible.
- **Dónde se emite:** Hook `useFlowTracking(flow)` en los formularios (ver `flow_started`). Se emite una vez por `flowInstanceId` si el usuario sale (cambio de ruta, cierre de pestaña vía `pagehide`, caducidad de sesión o 10 min sin actividad) con el formulario modificado y sin `flow_completed`.
- **Entrega (batch, diario):** El abandono se estudia sobre cientos de casos para rediseñar un formulario; ninguna acción depende de saberlo al instante.
- **Throttle / debounce:** Una emisión por instancia de flujo; se envía con `navigator.sendBeacon` para no perderlo al cerrar la pestaña.
- **Datos sensibles:** Sin PII. **No** se envían valores de los campos: solo cuántos se tocaron.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `flow` | texto | sí | Flujo abandonado. (valores: `outbound_order`, `inbound_order`, `incident_report`, `csv_analysis`, `registration`, `password_reset`, `password_change`) |
| `flowInstanceId` | texto | sí | UUID de la instancia, el mismo de `flow_started`. (formato validado por patrón) |
| `lastStep` | texto | sí | Último estado alcanzado. (valores: `editing`, `ready_to_submit`, `submit_rejected`) |
| `fieldsTouchedCount` | entero | sí | Cuántos campos modificó el usuario. (≥ 0) |
| `elapsedMs` | entero | sí | Milisegundos desde `flow_started`. (≥ 0) |
| `exitTrigger` | texto | sí | Qué provocó la salida. (valores: `navigation_away`, `tab_closed`, `session_expired`, `idle_timeout`) |
| `hadSubmitError` | booleano | sí | Si el servidor rechazó al menos un envío antes de salir. |

### 5.8 `inbound_order_created`

**Negocio · inventario** · **oportunidad** · emite: **backend** · entrega: **batch** (diario)

> Capturamos `inbound_order_created` porque necesitamos saber cuánto stock entra por insumo y restaurante y qué proporción de entradas se registra sin proveedor, lo que nos permite tomar la decisión de hacer obligatorio el proveedor y enlazarlo con el módulo de proveedores para poder medir la fiabilidad de cada uno.

- **Situación actual:** El campo `supplier` de la entrada es texto libre, opcional y sin enlace al directorio de proveedores: hoy no se puede cruzar una entrada con un proveedor real.
- **Dónde se emite:** `create_inbound_order`, tras `commit()`. `stockAfter` requiere llamar a `repository.get_current_stock` una vez más.
- **Entrega (batch, diario):** Se usa para planificar compras y negociar con proveedores, decisiones semanales.
- **Throttle / debounce:** Ninguno.
- **Datos sensibles:** Sin PII. El nombre del proveedor (texto libre) no se emite en la v1: solo `supplierProvided`.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `entryId` | entero | sí | `IngredientEntry.id`. (≥ 1) |
| `ingredientId` | entero | sí | Insumo. (≥ 1) |
| `restaurant` | texto | sí | Restaurante del insumo. (máx. 64 car.) |
| `quantity` | número | sí | Cantidad recibida (> 0). (> 0) |
| `stockAfter` | número | sí | Stock tras la entrada. (≥ 0) |
| `supplierProvided` | booleano | sí | Si se indicó proveedor. |

### 5.9 `ingredient_created`

**Negocio · inventario** · **oportunidad** · emite: **backend** · entrega: **batch** (diario)

> Capturamos `ingredient_created` porque necesitamos saber quién da de alta insumos y con qué frecuencia, lo que nos permite tomar la decisión de restringir el alta de insumos a administradores o guardar el creador como auditoría.

- **Situación actual:** `POST /inventory/products` solo exige estar autenticado (no comprueba el rol) y el insumo no guarda quién lo creó, a diferencia de las órdenes, que guardan `user_uuid`.
- **Dónde se emite:** `create_product`, tras `commit()`. Hay que añadir `current_user=Depends(get_current_user)` como parámetro del handler (FastAPI reutiliza la dependencia ya resuelta por el router, sin decodificar el token dos veces).
- **Entrega (batch, diario):** El alta de insumos es esporádica; se revisa en el informe diario.
- **Throttle / debounce:** Ninguno.
- **Datos sensibles:** Sin PII. No se emiten `name` ni `sku`.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `ingredientId` | entero | sí | Insumo creado. (≥ 1) |
| `restaurant` | texto | sí | Restaurante asignado. (máx. 64 car.) |
| `creatorRole` | texto | sí | Rol del usuario que lo creó. (valores: `admin`, `user`) |

### 5.10 `outbound_overdraw_warning_shown`

**Negocio · inventario** · **oportunidad** · emite: **frontend** · entrega: **batch** (diario)

> Capturamos `outbound_overdraw_warning_shown` porque necesitamos saber con qué frecuencia los operadores piden más cantidad de la disponible, es decir, si el stock que ven no coincide con lo que hay en cocina, lo que nos permite tomar la decisión de añadir un botón «sacar todo lo disponible», un recuento físico periódico o un stock de seguridad visible.

- **Situación actual:** El formulario de salida ya avisa y bloquea el envío si la cantidad supera el stock mostrado, pero ese aviso no se mide.
- **Dónde se emite:** `uis/backoffice/components/inventory-outbound-form.tsx`: cuando `quantityExceedsStock` pasa a verdadero (`trigger = typing`) y cuando `submit` se interrumpe por esa causa (`trigger = submit_blocked`).
- **Entrega (batch, diario):** Mide un hábito de uso (cuántas veces se corrige a mano), no una urgencia.
- **Throttle / debounce:** Debounce de 1 s tras dejar de teclear; como máximo una vez por insumo y por apertura del formulario.
- **Datos sensibles:** Sin PII.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `ingredientId` | entero | sí | Insumo seleccionado. (≥ 1) |
| `requestedQuantity` | número | sí | Cantidad escrita. |
| `availableStock` | número | sí | Stock que mostraba la interfaz. (≥ 0) |
| `trigger` | texto | sí | Qué lo provocó. (valores: `typing`, `submit_blocked`) |

### 5.11 `stock_snapshot_recorded`

**Negocio · inventario** · **oportunidad** · emite: **job** · entrega: **batch** (diario)

> Capturamos `stock_snapshot_recorded` porque necesitamos saber cómo evoluciona el nivel de stock por restaurante a lo largo del tiempo y qué restaurantes están crónicamente en nivel bajo, lo que nos permite tomar la decisión de fijar umbrales por restaurante o insumo en lugar de uno global y priorizar la reposición donde el nivel bajo es crónico.

- **Situación actual:** El stock se calcula al momento (entradas − salidas): no existe histórico, solo el valor de hoy.
- **Dónde se emite:** Tarea programada diaria a las 02:00 UTC (fuera del servicio web). Agrega `repository.list_ingredients_with_stock` por restaurante con los umbrales de `stock_threshold_triggered`. `sessionId` y `userId` valen `system`; `requestId` es un UUID por ejecución.
- **Entrega (batch, diario):** Es una foto diaria por definición; su valor está en la serie histórica.
- **Throttle / debounce:** Un evento por restaurante y día (14 al día).
- **Datos sensibles:** Sin PII.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `restaurant` | texto | sí | Restaurante agregado. (máx. 64 car.) |
| `ingredientsTotal` | entero | sí | Insumos del restaurante. (≥ 0) |
| `zeroCount` | entero | sí | Insumos con stock 0. (≥ 0) |
| `criticalCount` | entero | sí | Insumos con stock ≤ 10 (incluye los de stock 0). (≥ 0) |
| `lowCount` | entero | sí | Insumos con stock entre 11 y 30. (≥ 0) |
| `healthyCount` | entero | sí | Insumos con stock > 30. (≥ 0) |

### 5.12 `incident_created`

**Negocio · incidencias** · **oportunidad** · emite: **backend + frontend** · entrega: **batch** (diario)

> Capturamos `incident_created` porque necesitamos saber cuántas incidencias se crean por sede, origen y categoría, y qué sedes generan más fallos operativos frente a quejas, lo que nos permite tomar la decisión de dirigir mantenimiento o formación a las sedes con más fallos operativos y medir si bajan.

- **Situación actual:** El panel de incidencias muestra el estado actual, no la tasa de creación a lo largo del tiempo.
- **Dónde se emite:** `services/api/app/incidents/routes.py` → `create_incident`, tras guardar.
- **Entrega (batch, diario):** La asignación de recursos se revisa por semanas, no por minutos.
- **Throttle / debounce:** Ninguno.
- **Datos sensibles:** **Ni `title` ni `description` se emiten**: en incidencias de clientes pueden contener nombres, teléfonos o emails.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `incidentId` | entero | sí | Id de la incidencia. (≥ 1) |
| `category` | texto | sí | Categoría. (valores: `Queja`, `Solicitud`, `Fallo operativo`) |
| `origin` | texto | sí | Origen. (valores: `customer`, `branch`, `internal`) |
| `branch` | texto | sí | Sede. (valores: `central`, `Brasaland El Poblado`, `Brasaland Laureles`, `Brasaland Envigado`, `Brasaland Sabaneta`, `Brasaland Usaquén`, `Brasaland Chapinero`, `Brasaland Zona Rosa`, `Brasaland Granada`, `Brasaland Ciudad Jardín`, `Brasaland Unicentro`, `Brasaland Brickell`, `Brasaland Coral Gables`, `Brasaland Downtown`, `Brasaland International Drive`) |

### 5.13 `incident_status_changed`

**Negocio · incidencias** · **oportunidad** · emite: **backend + frontend** · entrega: **batch** (cada hora)

> Capturamos `incident_status_changed` porque necesitamos saber cuánto tarda una incidencia en resolverse según su categoría y cuántas se descartan, lo que nos permite tomar la decisión de definir un objetivo de tiempo de resolución por categoría y escalar las que lo superen.

- **Situación actual:** Se guardan el estado actual y las fechas, pero no se calcula ningún tiempo de resolución.
- **Dónde se emite:** `update_incident_status`, solo cuando el estado cambia de verdad (el caso sin cambio no emite, igual que no invalida la caché).
- **Entrega (batch, cada hora):** El tiempo de resolución alimenta un panel de seguimiento durante la jornada; no requiere segundos.
- **Throttle / debounce:** Ninguno.
- **Datos sensibles:** Sin PII.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `incidentId` | entero | sí | Incidencia. (≥ 1) |
| `fromStatus` | texto | sí | Estado anterior. (valores: `open`, `in_progress`, `resolved`, `discarded`) |
| `toStatus` | texto | sí | Estado nuevo. (valores: `open`, `in_progress`, `resolved`, `discarded`) |
| `category` | texto | sí | Categoría de la incidencia. (valores: `Queja`, `Solicitud`, `Fallo operativo`) |
| `ageHours` | número | sí | Horas desde la creación hasta el cambio. (≥ 0) |

### 5.14 `incident_csv_analyzed`

**Negocio · incidencias** · **oportunidad** · emite: **backend + frontend** · entrega: **batch** (diario)

> Capturamos `incident_csv_analyzed` porque necesitamos saber con qué frecuencia el CSV se rechaza o trae una proporción alta de filas inválidas, lo que nos permite tomar la decisión de arreglar la exportación de origen o mejorar los mensajes de validación del análisis.

- **Situación actual:** El análisis devuelve conteos al usuario pero no queda registro de cuántos ficheros fallan ni por qué.
- **Dónde se emite:** `services/api/app/main.py` → `analyze_incidents`, en todas sus salidas (éxito y los cuatro rechazos: extensión, vacío, codificación, formato).
- **Entrega (batch, diario):** Se revisa la calidad de los ficheros por semanas.
- **Throttle / debounce:** Ninguno.
- **Datos sensibles:** **No** se emiten nombre de fichero ni filas (pueden contener datos de clientes); solo conteos y tamaño.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `outcome` | texto | sí | Resultado. (valores: `analyzed`, `rejected_extension`, `rejected_empty`, `rejected_encoding`, `rejected_format`) |
| `fileSizeBytes` | entero | no | Tamaño del fichero (si se leyó). (≥ 0) |
| `totalRows` | entero | no | Filas procesadas (solo `analyzed`). (≥ 0) |
| `invalidRows` | entero | no | Filas inválidas (solo `analyzed`). (≥ 0) |
| `durationMs` | entero | sí | Duración del análisis en servidor. (≥ 0) |

### 5.15 `incident_list_filtered`

**Negocio · incidencias** · **oportunidad** · emite: **frontend** · entrega: **batch** (diario)

> Capturamos `incident_list_filtered` porque necesitamos saber qué filtros aplican los usuarios al listar incidencias y si repiten siempre los mismos, lo que nos permite tomar la decisión de cambiar los filtros por defecto o guardar vistas por usuario.

- **Situación actual:** La vista por defecto muestra todas las incidencias; no sabemos si esa es la que necesitan.
- **Dónde se emite:** `uis/backoffice/components/incident-list-panel.tsx`, al cambiar cualquier filtro.
- **Entrega (batch, diario):** Decide el diseño de la vista por defecto; no es urgente.
- **Throttle / debounce:** Debounce de 800 ms para no emitir en cada cambio intermedio.
- **Datos sensibles:** Sin PII. Solo qué filtros se usaron, no los valores libres (no hay filtros de texto libre).

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `filtersApplied` | lista | sí | Filtros activos tras el cambio (vacío = restablecer). (elementos: `status`, `origin`, `branch`) |
| `resultCount` | entero | sí | Filas devueltas. (≥ 0) |

### 5.16 `incident_results_exported`

**Negocio · incidencias** · **oportunidad** · emite: **backend** · entrega: **batch** (diario)

> Capturamos `incident_results_exported` porque necesitamos saber si exportar el resultado del análisis a CSV es un paso habitual, lo que nos permite tomar la decisión de construir un informe o panel recurrente en lugar de exportaciones manuales.

- **Situación actual:** `GET /api/incidents/results/export` existe pero no sabemos si se usa.
- **Dónde se emite:** `main.py` → `export_latest_results`, en la descarga correcta y en el `404` «todavía no hay análisis».
- **Entrega (batch, diario):** Es una señal de producto, no operativa.
- **Throttle / debounce:** Ninguno.
- **Datos sensibles:** Sin PII (el CSV exportado ya excluye datos de clientes; el evento solo cuenta filas).

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `outcome` | texto | sí | Resultado. (valores: `downloaded`, `no_analysis_available`) |
| `rowCount` | entero | no | Filas exportadas (solo `downloaded`). (≥ 0) |

### 5.17 `supplier_rate_updated`

**Negocio · proveedores** · **oportunidad** · emite: **backend** · entrega: **batch** (diario)

> Capturamos `supplier_rate_updated` porque necesitamos saber con qué frecuencia se editan las tarifas de los proveedores y de cuánto son los cambios, lo que nos permite tomar la decisión de añadir historial de tarifas con auditoría y alertar cuando un cambio supere un porcentaje.

- **Situación actual:** La tarifa se sobrescribe con `PATCH /{supplier_id}/rate`: no queda historial de valores anteriores.
- **Dónde se emite:** `services/api/app/suppliers/routes.py` → `PATCH /{supplier_id}/rate`, tras guardar.
- **Entrega (batch, diario):** Se revisa en negociación de contratos, no en tiempo real.
- **Throttle / debounce:** Ninguno.
- **Datos sensibles:** Sin PII (proveedores = empresas). No se emite el nombre; solo el id.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `supplierId` | entero | sí | Proveedor. (≥ 1) |
| `country` | texto | sí | País del proveedor. (valores: `Colombia`, `Estados Unidos`) |
| `previousRate` | número | sí | Tarifa anterior. (≥ 0) |
| `newRate` | número | sí | Tarifa nueva. (≥ 0) |

### 5.18 `login_succeeded`

**Autenticación** · **oportunidad** · emite: **backend + frontend** · entrega: **batch** (diario)

> Capturamos `login_succeeded` porque necesitamos saber cuántos inicios de sesión correctos hay por día, para calcular la proporción de fallos y cuánta gente usa el backoffice, lo que nos permite tomar la decisión de calibrar el umbral de bloqueo por intentos fallidos y dimensionar el soporte de acceso.

- **Situación actual:** Es el denominador de `login_failed`: sin él, 50 fallos no se pueden interpretar.
- **Dónde se emite:** `auth/routes.py` → `login`, antes de devolver el token.
- **Entrega (batch, diario):** Es el denominador de `login_failed`; se calcula la tasa diaria.
- **Throttle / debounce:** Ninguno.
- **Datos sensibles:** Sin PII adicional (el `userId` seudónimo ya va en el envelope).

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `tokenTtlMinutes` | entero | sí | Vigencia del token emitido (`ACCESS_TOKEN_EXPIRE_MINUTES`, hoy 30). (≥ 1) |

### 5.19 `session_expired`

**Autenticación** · **oportunidad** · emite: **frontend** · entrega: **batch** (diario)

> Capturamos `session_expired` porque necesitamos saber con qué frecuencia caduca la sesión (token de 30 minutos) con trabajo en curso, lo que nos permite tomar la decisión de alargar la vigencia, añadir renovación silenciosa del token o avisar antes de caducar.

- **Situación actual:** `apiFetch` ante un 401 limpia el token y redirige a login sin aviso; un formulario a medias se pierde.
- **Dónde se emite:** `uis/backoffice/lib/api-client.ts` → `apiFetch`, en la rama `401` de una petición autenticada, justo antes de `redirectToLogin()`.
- **Entrega (batch, diario):** Se estudia el patrón para decidir una política de sesión; no requiere inmediatez.
- **Throttle / debounce:** Una vez por sesión (tras emitirlo se redirige a login).
- **Datos sensibles:** Sin PII.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `section` | texto | sí | Sección donde ocurrió. (valores: `dashboard`, `suppliers`, `incident_analysis`, `incidents_manager`, `incident_new`, `inventory_products`, `inventory_orders`, `inventory_inbound`, `inventory_outbound`, `account_profile`, `account_password`, `login`, `register`, `forgot_password`, `reset_password`) |
| `sessionAgeMinutes` | número | sí | Minutos desde el último inicio de sesión. (≥ 0) |
| `formDirty` | booleano | sí | Si había un formulario modificado sin enviar. |
| `flow` | texto | no | Flujo en curso, si lo había. (valores: `outbound_order`, `inbound_order`, `incident_report`, `csv_analysis`, `registration`, `password_reset`, `password_change`) |

### 5.20 `password_reset_requested`

**Autenticación** · **oportunidad** · emite: **backend + frontend** · entrega: **batch** (cada hora)

> Capturamos `password_reset_requested` porque necesitamos saber cuántas solicitudes de restablecimiento son de correos no registrados (sondeo) y cuántas fallan al enviar el email, lo que nos permite tomar la decisión de alertar de los fallos de envío y limitar las solicitudes por origen.

- **Situación actual:** Si el envío falla (Resend), el error solo se escribe en el log del servidor y el usuario ve el mismo mensaje de éxito.
- **Dónde se emite:** `auth/routes.py` → `forgot_password`, tras intentar el envío. La respuesta al cliente no cambia (sigue sin revelar si el correo existe).
- **Entrega (batch, cada hora):** Un fallo de envío deja a usuarios sin poder entrar durante horas; el corte horario permite reaccionar en la misma jornada.
- **Throttle / debounce:** Ninguno.
- **Datos sensibles:** **Sí, seudonimizado.** No se guarda el email; `accountKnown` es información interna que nunca se devuelve al cliente.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `accountKnown` | booleano | sí | Si el email correspondía a una cuenta. |
| `emailSendOutcome` | texto | sí | Resultado del envío. (valores: `sent`, `send_failed`, `not_attempted`) |

### 5.21 `password_reset_completed`

**Autenticación** · **oportunidad** · emite: **backend + frontend** · entrega: **batch** (diario)

> Capturamos `password_reset_completed` porque necesitamos saber qué parte de los restablecimientos solicitados se completa y cuánto tarda la gente en usar el enlace, lo que nos permite tomar la decisión de ajustar la caducidad del enlace (30 min) o simplificar el proceso.

- **Situación actual:** Hoy no se relaciona la solicitud con la finalización.
- **Dónde se emite:** `reset_password`, tras actualizar la contraseña y marcar el token como usado.
- **Entrega (batch, diario):** Mide la tasa de finalización del flujo.
- **Throttle / debounce:** Ninguno.
- **Datos sensibles:** Sin PII adicional.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `tokenAgeMinutes` | número | sí | Minutos entre la solicitud y el uso del enlace. (≥ 0) |

### 5.22 `password_reset_failed`

**Autenticación** · **oportunidad** · emite: **backend + frontend** · entrega: **batch** (diario)

> Capturamos `password_reset_failed` porque necesitamos saber por qué fallan los enlaces de restablecimiento: caducados, ya usados o inválidos, lo que nos permite tomar la decisión de alargar la caducidad o mostrar un mensaje distinto según la causa.

- **Situación actual:** El endpoint devuelve el mismo 400 para las tres causas, así que no se distinguen.
- **Dónde se emite:** `reset_password`, en la rama `400` de enlace inválido o caducado (hoy una sola respuesta para tres causas).
- **Entrega (batch, diario):** Decide un ajuste de política, no una acción inmediata.
- **Throttle / debounce:** Ninguno.
- **Datos sensibles:** Sin PII. El token nunca se emite (ni en claro ni su hash).

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `failureReason` | texto | sí | Causa. (valores: `invalid_token`, `expired_token`, `used_token`) |
| `tokenAgeMinutes` | número | no | Antigüedad del token, si existía. (≥ 0) |

### 5.23 `user_registered`

**Autenticación** · **oportunidad** · emite: **backend + frontend** · entrega: **batch** (cada hora)

> Capturamos `user_registered` porque necesitamos saber cuántas cuentas nuevas se crean por día y si hay altas inesperadas, lo que nos permite tomar la decisión de cerrar el registro público o exigir invitación o aprobación de un administrador.

- **Situación actual:** `POST /users` es público y una cuenta nueva ya puede iniciar sesión en un backoffice con datos operativos.
- **Dónde se emite:** `services/api/app/users/routes.py` → `create_user`, en el alta y en el `409` de email ya registrado.
- **Entrega (batch, cada hora):** Una oleada de altas desconocidas conviene verla el mismo día; un corte horario es suficiente y más barato que streaming.
- **Throttle / debounce:** Ninguno.
- **Datos sensibles:** **Sí, derivado.** No se emiten nombre, email, teléfono ni dirección: solo si se rellenaron (`hasPhone`, `hasAddress`).

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `registrationOutcome` | texto | sí | Resultado. (valores: `created`, `email_already_registered`) |
| `hasPhone` | booleano | sí | Si el perfil incluye teléfono. |
| `hasAddress` | booleano | sí | Si el perfil incluye dirección. |

### 5.24 `api_latency_recorded`

**Rendimiento** · **oportunidad** · emite: **backend + frontend** · entrega: **batch** (cada hora)

> Capturamos `api_latency_recorded` porque necesitamos saber qué endpoints son lentos o crecen con el volumen de datos en producción, lo que nos permite tomar la decisión de elegir qué endpoint paginar o cachear a continuación con datos reales.

- **Situación actual:** Con datos de prueba, `/inventory/orders` tarda 503 ms y devuelve 3 MB con 20 000 movimientos (`CACHING_REPORT.md` del PR #12); en producción no se mide.
- **Dónde se emite:** Middleware HTTP de `main.py`. Si el PR #12 (caché) ya está fusionado, se amplía el middleware de tiempos que ya mide con `perf_counter` y escribe `X-Process-Time-Ms`; si no, se crea uno equivalente. `cache` sale de la cabecera de respuesta `X-Cache` (que solo fija ese PR en el listado de incidencias); `none` si no está.
- **Entrega (batch, cada hora):** El dato sirve para priorizar optimizaciones y vigilar tendencias; una alerta de caída de servicio ya la da `api_unhandled_error_raised`.
- **Throttle / debounce:** Muestreo: 100 % de peticiones con `durationMs > 500` o `statusClass = 5xx`; 5 % del resto (`sampleRate` = 1 o 0.05, para poder reescalar).
- **Datos sensibles:** Sin PII. Siempre la **plantilla** de ruta (`/inventory/products/{ingredient_id}`), nunca la ruta real ni la query string.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `method` | texto | sí | Método HTTP. (valores: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`) |
| `routeTemplate` | texto | sí | Plantilla de ruta de FastAPI. (formato validado por patrón; máx. 96 car.) |
| `statusClass` | texto | sí | Familia del código de estado. (valores: `2xx`, `3xx`, `4xx`, `5xx`) |
| `durationMs` | número | sí | Tiempo de servidor en ms. (≥ 0) |
| `responseBytes` | entero | no | Tamaño de la respuesta si se conoce (`Content-Length`). (≥ 0) |
| `cache` | texto | no | Resultado de caché (`none` si el endpoint no usa caché). (valores: `hit`, `miss`, `none`) |
| `sampleRate` | número | sí | Probabilidad con la que se muestreó (1 o 0.05). (valores: `1`, `0.05`) |

### 5.25 `web_vital_measured`

**Rendimiento** · **oportunidad** · emite: **frontend** · entrega: **batch** (diario)

> Capturamos `web_vital_measured` porque necesitamos saber qué pantallas del backoffice se sienten lentas en los equipos y redes reales de los restaurantes, lo que nos permite tomar la decisión de optimizar esas pantallas (carga diferida, memoización, paginación) con datos de campo.

- **Situación actual:** Las auditorías Lighthouse son de laboratorio, con un solo equipo y una red simulada.
- **Dónde se emite:** `useReportWebVitals` de Next.js en un componente cliente del `layout.tsx` raíz.
- **Entrega (batch, diario):** Las métricas de campo se evalúan por percentiles sobre muchos usuarios; un único valor no se actúa.
- **Throttle / debounce:** Una emisión por métrica y carga de página (las métricas finales `INP`/`CLS` se envían al ocultarse la página, con `sendBeacon`).
- **Datos sensibles:** Sin PII. Plantilla de ruta, sin parámetros.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `metric` | texto | sí | Métrica. (valores: `LCP`, `INP`, `CLS`, `FCP`, `TTFB`) |
| `value` | número | sí | Valor (ms; adimensional en CLS). (≥ 0) |
| `rating` | texto | sí | Clasificación de Web Vitals. (valores: `good`, `needs-improvement`, `poor`) |
| `routeTemplate` | texto | sí | Plantilla de la ruta de Next. (formato validado por patrón; máx. 96 car.) |
| `navigationType` | texto | sí | Tipo de navegación. (valores: `navigate`, `reload`, `back-forward`, `prerender`, `restore`) |

### 5.26 `api_unhandled_error_raised`

**Errores** · **oportunidad** · emite: **backend** · entrega: **stream** (≤ 60 s)

> Capturamos `api_unhandled_error_raised` porque necesitamos saber con qué frecuencia ocurren errores 500 y cuáles se repiten, lo que nos permite tomar la decisión de avisar al responsable de guardia en minutos y priorizar el arreglo de los errores más repetidos.

- **Situación actual:** El cliente solo recibe un mensaje genérico (por diseño) y el detalle queda únicamente en el log de uvicorn.
- **Dónde se emite:** `main.py` → `unhandled_exception_handler`, junto al `logger.exception` existente.
- **Entrega (stream, ≤ 60 s):** Un 500 repetido es una caída parcial; los restaurantes no pueden esperar al informe del día siguiente.
- **Throttle / debounce:** Deduplicación por `fingerprint`: máximo 1 evento por huella y minuto, con el número de repeticiones agregado en el procesador.
- **Datos sensibles:** Sin PII. **No** se emiten el mensaje de la excepción ni el traceback (pueden contener datos de usuarios o SQL con valores); el detalle sigue solo en el log del servidor.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `method` | texto | sí | Método HTTP. (valores: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`) |
| `routeTemplate` | texto | sí | Plantilla de ruta. (formato validado por patrón; máx. 96 car.) |
| `exceptionType` | texto | sí | Nombre de la clase de la excepción. (formato validado por patrón; máx. 96 car.) |
| `fingerprint` | texto | sí | Huella estable: 16 hex de SHA-256(`exceptionType` + archivo + línea). (formato validado por patrón) |

### 5.27 `frontend_error_captured`

**Errores** · **oportunidad** · emite: **frontend** · entrega: **batch** (cada hora)

> Capturamos `frontend_error_captured` porque necesitamos saber qué errores de JavaScript ocurren en el navegador y a cuántas sesiones afectan, lo que nos permite tomar la decisión de corregir primero los que más sesiones afectan y detectar regresiones tras cada despliegue.

- **Situación actual:** No hay `app/error.tsx` ni captura global de errores: solo los ve el usuario.
- **Dónde se emite:** Nuevo `app/error.tsx` (error boundary) y listeners de `window.onerror` y `unhandledrejection` en un componente cliente del layout.
- **Entrega (batch, cada hora):** Priorizar arreglos de frontend se decide por ranking diario; un corte horario permite detectar un despliegue roto en la misma jornada.
- **Throttle / debounce:** Máximo 20 eventos por sesión y 1 por `fingerprint` cada 60 s, para no inundar si un error se repite en bucle.
- **Datos sensibles:** Sin PII. **No** se envían `error.message` ni el stack completo (pueden incluir datos de formularios o URLs con tokens); solo nombre del error y el primer frame de la app, sin URL ni query.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `errorSource` | texto | sí | Origen de la captura. (valores: `error_boundary`, `window_error`, `unhandled_rejection`) |
| `errorName` | texto | sí | `error.name` (p. ej. `TypeError`). (formato validado por patrón; máx. 64 car.) |
| `fingerprint` | texto | sí | 16 hex de SHA-256(`errorName` + `topFrame`). (formato validado por patrón) |
| `topFrame` | texto | no | Archivo y línea del primer frame de la app, sin URL (`inventory-outbound-form.tsx:84`). (formato validado por patrón; máx. 128 car.) |
| `routeTemplate` | texto | sí | Plantilla de la ruta de Next. (formato validado por patrón; máx. 96 car.) |

### 5.28 `network_request_failed`

**Errores** · **oportunidad** · emite: **frontend** · entrega: **batch** (diario)

> Capturamos `network_request_failed` porque necesitamos saber con qué frecuencia falla la conexión entre el navegador y la API, y desde qué situaciones (sin conexión, tiempo agotado), lo que nos permite tomar la decisión de añadir reintento automático, guardar borradores de formularios o revisar la conectividad de ciertos locales.

- **Situación actual:** Un fallo de red nunca llega al servidor; cada formulario solo muestra «No se pudo conectar con el servidor».
- **Dónde se emite:** `lib/api-client.ts` → `apiFetch`, cuando `fetch` lanza excepción (hoy cada formulario muestra «No se pudo conectar con el servidor» sin dejar rastro).
- **Entrega (batch, diario):** Se analiza la tendencia por local y franja horaria; no se actúa sobre un fallo aislado.
- **Throttle / debounce:** Máximo 1 evento por `routeTemplate` cada 30 s y 10 por sesión.
- **Datos sensibles:** Sin PII. Plantilla de ruta, nunca la URL real.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `method` | texto | sí | Método HTTP. (valores: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`) |
| `routeTemplate` | texto | sí | Plantilla de ruta de la API. (formato validado por patrón; máx. 96 car.) |
| `errorKind` | texto | sí | Tipo de fallo. (valores: `network`, `timeout`) |
| `online` | booleano | sí | `navigator.onLine` en ese momento. |
| `elapsedMs` | entero | sí | Milisegundos hasta el fallo. (≥ 0) |

### 5.29 `request_validation_failed`

**Errores** · **oportunidad** · emite: **backend** · entrega: **batch** (diario)

> Capturamos `request_validation_failed` porque necesitamos saber qué campos fallan más la validación del servidor, lo que nos permite tomar la decisión de mejorar el texto de ayuda, el formato esperado o la validación en el cliente de esos campos.

- **Situación actual:** El handler devuelve el 400 pero no deja constancia de qué campos fallan con más frecuencia.
- **Dónde se emite:** Handler `RequestValidationError` de `main.py` (el que ya responde `400`), **salvo** las rutas de órdenes de inventario (las cubre `inventory_validation_failed`) y los intentos de editar stock (los cubre `direct_stock_edit_rejected`).
- **Entrega (batch, diario):** Es una mejora de usabilidad que se decide con el ranking semanal de campos.
- **Throttle / debounce:** Ninguno.
- **Datos sensibles:** Sin PII. Solo **nombres** de campo y tipos de error de Pydantic; nunca el valor enviado (`input`) ni el mensaje (`msg`).

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `method` | texto | sí | Método HTTP. (valores: `POST`, `PUT`, `PATCH`) |
| `routeTemplate` | texto | sí | Plantilla de ruta. (formato validado por patrón; máx. 96 car.) |
| `failedFields` | lista | sí | Campos inválidos (nombres, máximo 20). (máx. 20 elementos) |
| `errorTypes` | lista | sí | Tipos de error de Pydantic (p. ej. `missing`, `string_too_short`). (máx. 20 elementos) |

### 5.30 `flow_started`

**Navegación y flujos** · **oportunidad** · emite: **frontend** · entrega: **batch** (diario)

> Capturamos `flow_started` porque necesitamos saber cuántos flujos se empiezan, para calcular la tasa de finalización y de abandono, lo que nos permite tomar la decisión de comparar los flujos entre sí y elegir cuál rediseñar primero.

- **Situación actual:** Es el denominador del embudo de `flow_completed` y `flow_abandoned`.
- **Dónde se emite:** Hook `useFlowTracking(flow)` en: `inventory-outbound-form.tsx` (`outbound_order`), `inventory-inbound-form.tsx` (`inbound_order`), `incident-form.tsx` (`incident_report`), `incident-analysis.tsx` (`csv_analysis`: al elegir fichero), `register-form.tsx` (`registration`), `forgot-password-form.tsx` (`password_reset`) y `change-password-form.tsx` (`password_change`). Se emite en la **primera modificación** de un campo, no al abrir la página (eso lo cubre `navigation_section_viewed`).
- **Entrega (batch, diario):** Es el denominador del embudo; se calcula por día.
- **Throttle / debounce:** Una emisión por instancia (`flowInstanceId` nuevo cada vez que el formulario vuelve a estado limpio).
- **Datos sensibles:** Sin PII.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `flow` | texto | sí | Flujo iniciado. (valores: `outbound_order`, `inbound_order`, `incident_report`, `csv_analysis`, `registration`, `password_reset`, `password_change`) |
| `flowInstanceId` | texto | sí | UUID v4 de esta instancia. (formato validado por patrón) |
| `section` | texto | sí | Sección donde ocurre. (valores: `dashboard`, `suppliers`, `incident_analysis`, `incidents_manager`, `incident_new`, `inventory_products`, `inventory_orders`, `inventory_inbound`, `inventory_outbound`, `account_profile`, `account_password`, `login`, `register`, `forgot_password`, `reset_password`) |

### 5.31 `flow_completed`

**Navegación y flujos** · **oportunidad** · emite: **frontend** · entrega: **batch** (diario)

> Capturamos `flow_completed` porque necesitamos saber cuánto tarda y cuántos intentos exige terminar cada flujo, lo que nos permite tomar la decisión de localizar los pasos que más tiempo o reintentos exigen y simplificarlos.

- **Situación actual:** Los eventos de servidor cuentan órdenes, pero no cuántos envíos costó cada una.
- **Dónde se emite:** El mismo hook, cuando el servidor responde con éxito al envío. El evento de servidor (`outbound_order_created`, etc.) sigue siendo la fuente de verdad para volúmenes; este mide la experiencia.
- **Entrega (batch, diario):** Se compara con `flow_started` y `flow_abandoned` en el informe diario.
- **Throttle / debounce:** Una emisión por instancia.
- **Datos sensibles:** Sin PII.

| Propiedad | Tipo | Oblig. | Descripción y restricciones |
|---|---|:-:|---|
| `flow` | texto | sí | Flujo completado. (valores: `outbound_order`, `inbound_order`, `incident_report`, `csv_analysis`, `registration`, `password_reset`, `password_change`) |
| `flowInstanceId` | texto | sí | UUID de la instancia, el de `flow_started`. (formato validado por patrón) |
| `elapsedMs` | entero | sí | Milisegundos desde `flow_started`. (≥ 0) |
| `submitAttempts` | entero | sí | Envíos necesarios (1 = a la primera). (≥ 1) |


## 6. Allowlist, privacidad y datos sensibles

### 6.1 Reglas globales

1. **Denegación por defecto.** Cada evento declara sus propiedades y `additionalProperties: false`. El emisor valida contra `event-schemas.json`: en desarrollo y test lanza un error; en producción **descarta el evento** y suma al contador `telemetry_rejected_total`. Un fallo de telemetría nunca puede romper la petición del usuario.
2. **Nunca aparecen**, ni como propiedad ni como valor: email, nombre, teléfono, dirección, contraseñas, tokens (de sesión o de restablecimiento, ni su hash), IP en claro, texto escrito por el usuario (`reason`, `supplier`, `title`, `description`, `name` de insumo), nombres de fichero, URLs reales o con query string, cuerpos de petición/respuesta, mensajes de excepción y *tracebacks*.
3. **Identificadores internos permitidos:** `userId`, `ingredientId`, `incidentId`, `supplierId` y los ids de orden. Son seudónimos: solo se pueden asociar a una persona consultando la base de datos de la aplicación.
4. **Enumeraciones cerradas** siempre que el dominio lo permite (secciones, flujos, estados, causas de error); las cadenas abiertas llevan patrón y longitud máxima.
5. **Cambios de allowlist** = PR con etiqueta `telemetry-schema` revisado por el responsable de datos.

### 6.2 Registro de datos sensibles y cómo se tratan

| Evento | Tratamiento |
|---|---|
| `outbound_order_created` | Sin PII. `reason` (texto libre) **no** se captura: puede contener nombres o datos personales; solo `reasonProvided`. |
| `inventory_validation_failed` | Sin PII. El texto del error HTTP (`detail`) **no** se captura: incluye el nombre del insumo y del restaurante en texto libre. |
| `direct_stock_edit_rejected` | Sin PII. Solo se guardan los **nombres** de los campos ofensivos (lista cerrada), nunca sus valores. |
| `stock_threshold_triggered` | Sin PII. |
| `login_failed` | **Sí, seudonimizado.** Nunca se guarda el email ni la IP. `accountKey` = primeros 16 hex de HMAC-SHA256(email en minúsculas, clave secreta de telemetría); `sourceKey` = ídem sobre la IP con una clave que rota cada día (permite correlacionar dentro del día, no seguir a una persona entre días). `userId` es siempre `anonymous` (una identificación fallida no es una sesión). |
| `navigation_section_viewed` | Sin PII. Solo valores de una lista cerrada; nunca la URL completa ni la query string. |
| `flow_abandoned` | Sin PII. **No** se envían valores de los campos: solo cuántos se tocaron. |
| `inbound_order_created` | Sin PII. El nombre del proveedor (texto libre) no se emite en la v1: solo `supplierProvided`. |
| `ingredient_created` | Sin PII. No se emiten `name` ni `sku`. |
| `outbound_overdraw_warning_shown` | Sin PII. |
| `stock_snapshot_recorded` | Sin PII. |
| `incident_created` | **Ni `title` ni `description` se emiten**: en incidencias de clientes pueden contener nombres, teléfonos o emails. |
| `incident_status_changed` | Sin PII. |
| `incident_csv_analyzed` | **No** se emiten nombre de fichero ni filas (pueden contener datos de clientes); solo conteos y tamaño. |
| `incident_list_filtered` | Sin PII. Solo qué filtros se usaron, no los valores libres (no hay filtros de texto libre). |
| `incident_results_exported` | Sin PII (el CSV exportado ya excluye datos de clientes; el evento solo cuenta filas). |
| `supplier_rate_updated` | Sin PII (proveedores = empresas). No se emite el nombre; solo el id. |
| `login_succeeded` | Sin PII adicional (el `userId` seudónimo ya va en el envelope). |
| `session_expired` | Sin PII. |
| `password_reset_requested` | **Sí, seudonimizado.** No se guarda el email; `accountKnown` es información interna que nunca se devuelve al cliente. |
| `password_reset_completed` | Sin PII adicional. |
| `password_reset_failed` | Sin PII. El token nunca se emite (ni en claro ni su hash). |
| `user_registered` | **Sí, derivado.** No se emiten nombre, email, teléfono ni dirección: solo si se rellenaron (`hasPhone`, `hasAddress`). |
| `api_latency_recorded` | Sin PII. Siempre la **plantilla** de ruta (`/inventory/products/{ingredient_id}`), nunca la ruta real ni la query string. |
| `web_vital_measured` | Sin PII. Plantilla de ruta, sin parámetros. |
| `api_unhandled_error_raised` | Sin PII. **No** se emiten el mensaje de la excepción ni el traceback (pueden contener datos de usuarios o SQL con valores); el detalle sigue solo en el log del servidor. |
| `frontend_error_captured` | Sin PII. **No** se envían `error.message` ni el stack completo (pueden incluir datos de formularios o URLs con tokens); solo nombre del error y el primer frame de la app, sin URL ni query. |
| `network_request_failed` | Sin PII. Plantilla de ruta, nunca la URL real. |
| `request_validation_failed` | Sin PII. Solo **nombres** de campo y tipos de error de Pydantic; nunca el valor enviado (`input`) ni el mensaje (`msg`). |
| `flow_started` | Sin PII. |
| `flow_completed` | Sin PII. |

**Seudonimización con clave:** `accountKey` y `sourceKey` son los primeros 16 caracteres hexadecimales de `HMAC-SHA256(valor, clave)`. La clave maestra (`TELEMETRY_HMAC_KEY`) vive solo en variables de entorno del servidor; para `sourceKey` se deriva una clave distinta por día, de modo que se puede correlacionar un origen dentro del día pero no seguir a una persona entre días.

### 6.3 Retención y baja de usuarios (propuesta a validar)

- Eventos sin procesar: **13 meses** (cubre comparaciones interanuales). Agregados: sin límite.
- `login_failed` (claves de cuenta y origen): **30 días**.
- Al borrar un usuario (`DELETE /users/{id}`), un proceso reescribe su `userId` a `deleted` en los eventos históricos.
- El acceso al almacén de telemetría es solo para el equipo técnico y de operaciones, con una cuenta de solo lectura para los paneles.

## 7. Estrategia de entrega: *stream* vs. *batch*

**Criterio:** un evento va por *stream* únicamente si existe una persona o un sistema que debe actuar **en menos de un minuto** y esperar al corte siguiente tendría un coste real (un restaurante sin un insumo, una cuenta atacada, una caída parcial). Todo lo demás es *batch*, con el corte más largo que no estropee la decisión.

| Evento | Modo | Latencia objetivo | Por qué (urgencia de la decisión) |
|---|---|---|---|
| `direct_stock_edit_rejected` | **stream** | ≤ 60 s | Es una señal de integridad: intentar saltarse la regla «el stock solo cambia por órdenes» una vez es una duda; repetido en minutos desde la misma cuenta puede ser un error de integración o un uso indebido, y hay que poder avisar mientras ocurre. |
| `stock_threshold_triggered` | **stream** | ≤ 60 s | Un restaurante sin un ingrediente base para la brasa no puede servir: la reposición se pide en horas, así que el aviso al encargado debe llegar en menos de un minuto; un informe diario llegaría después de que se agote. |
| `login_failed` | **stream** | ≤ 60 s | Detectar relleno de credenciales requiere contar intentos por ventana de minutos; con un informe diario el ataque ya habría terminado. |
| `api_unhandled_error_raised` | **stream** | ≤ 60 s | Un 500 repetido es una caída parcial; los restaurantes no pueden esperar al informe del día siguiente. |
| `outbound_order_created` | **batch** | cada hora | La pregunta de operaciones es «cuántas órdenes de salida por día»: una cifra diaria no cambia ninguna decisión en segundos; un corte horario alimenta el panel del turno sin coste de streaming. |
| `inventory_validation_failed` | **batch** | diario | Se analiza como ranking semanal de insumos problemáticos; nadie actúa sobre un rechazo concreto en minutos. |
| `navigation_section_viewed` | **batch** | diario | Es una pregunta de producto de largo plazo (qué secciones mantener): una agregación diaria basta. |
| `flow_abandoned` | **batch** | diario | El abandono se estudia sobre cientos de casos para rediseñar un formulario; ninguna acción depende de saberlo al instante. |
| `inbound_order_created` | **batch** | diario | Se usa para planificar compras y negociar con proveedores, decisiones semanales. |
| `ingredient_created` | **batch** | diario | El alta de insumos es esporádica; se revisa en el informe diario. |
| `outbound_overdraw_warning_shown` | **batch** | diario | Mide un hábito de uso (cuántas veces se corrige a mano), no una urgencia. |
| `stock_snapshot_recorded` | **batch** | diario | Es una foto diaria por definición; su valor está en la serie histórica. |
| `incident_created` | **batch** | diario | La asignación de recursos se revisa por semanas, no por minutos. |
| `incident_status_changed` | **batch** | cada hora | El tiempo de resolución alimenta un panel de seguimiento durante la jornada; no requiere segundos. |
| `incident_csv_analyzed` | **batch** | diario | Se revisa la calidad de los ficheros por semanas. |
| `incident_list_filtered` | **batch** | diario | Decide el diseño de la vista por defecto; no es urgente. |
| `incident_results_exported` | **batch** | diario | Es una señal de producto, no operativa. |
| `supplier_rate_updated` | **batch** | diario | Se revisa en negociación de contratos, no en tiempo real. |
| `login_succeeded` | **batch** | diario | Es el denominador de `login_failed`; se calcula la tasa diaria. |
| `session_expired` | **batch** | diario | Se estudia el patrón para decidir una política de sesión; no requiere inmediatez. |
| `password_reset_requested` | **batch** | cada hora | Un fallo de envío deja a usuarios sin poder entrar durante horas; el corte horario permite reaccionar en la misma jornada. |
| `password_reset_completed` | **batch** | diario | Mide la tasa de finalización del flujo. |
| `password_reset_failed` | **batch** | diario | Decide un ajuste de política, no una acción inmediata. |
| `user_registered` | **batch** | cada hora | Una oleada de altas desconocidas conviene verla el mismo día; un corte horario es suficiente y más barato que streaming. |
| `api_latency_recorded` | **batch** | cada hora | El dato sirve para priorizar optimizaciones y vigilar tendencias; una alerta de caída de servicio ya la da `api_unhandled_error_raised`. |
| `web_vital_measured` | **batch** | diario | Las métricas de campo se evalúan por percentiles sobre muchos usuarios; un único valor no se actúa. |
| `frontend_error_captured` | **batch** | cada hora | Priorizar arreglos de frontend se decide por ranking diario; un corte horario permite detectar un despliegue roto en la misma jornada. |
| `network_request_failed` | **batch** | diario | Se analiza la tendencia por local y franja horaria; no se actúa sobre un fallo aislado. |
| `request_validation_failed` | **batch** | diario | Es una mejora de usabilidad que se decide con el ranking semanal de campos. |
| `flow_started` | **batch** | diario | Es el denominador del embudo; se calcula por día. |
| `flow_completed` | **batch** | diario | Se compara con `flow_started` y `flow_abandoned` en el informe diario. |

### 7.1 Reglas de alerta de los eventos en *stream* (valores iniciales, a ajustar tras 30 días de datos)

| Evento | Regla | Destinatario |
|---|---|---|
| `stock_threshold_triggered` | Cada evento avisa; si el mismo insumo cruza `critical`, el aviso se marca urgente. | Encargado del restaurante afectado y compras |
| `direct_stock_edit_rejected` | 3 o más intentos del mismo `userId` en 10 minutos. | Administrador |
| `login_failed` | 5 o más por `accountKey` o 20 o más por `sourceKey` en 10 minutos. | Administrador (y, si se decide, bloqueo temporal) |
| `api_unhandled_error_raised` | 3 o más con el mismo `fingerprint` en 5 minutos, o cualquier error en `/auth/login`. | Responsable de guardia |

### 7.2 Estrategia de *throttle* / *debounce*

| Evento | Estrategia |
|---|---|
| `direct_stock_edit_rejected` | Sin throttle (evento raro). El procesador de stream agrupa por `userId` y avisa a partir de 3 intentos en 10 minutos. |
| `stock_threshold_triggered` | Disparo por **cruce** (edge-triggered), no por nivel: no se repite mientras el stock siga por debajo; solo se vuelve a emitir tras recuperarse por encima del umbral. Evita inundar el canal con cada lectura. |
| `login_failed` | Sin throttle: es baja frecuencia y cada intento cuenta. Si hubiera un ataque, el procesador agrega y el almacenamiento aplica el tope de volumen (ver sección 7). |
| `navigation_section_viewed` | Deduplicar: misma sección dentro de 30 s (re-render, cambio de hash, volver a la pestaña) no vuelve a emitir. |
| `flow_abandoned` | Una emisión por instancia de flujo; se envía con `navigator.sendBeacon` para no perderlo al cerrar la pestaña. |
| `outbound_overdraw_warning_shown` | Debounce de 1 s tras dejar de teclear; como máximo una vez por insumo y por apertura del formulario. |
| `stock_snapshot_recorded` | Un evento por restaurante y día (14 al día). |
| `incident_list_filtered` | Debounce de 800 ms para no emitir en cada cambio intermedio. |
| `session_expired` | Una vez por sesión (tras emitirlo se redirige a login). |
| `api_latency_recorded` | Muestreo: 100 % de peticiones con `durationMs > 500` o `statusClass = 5xx`; 5 % del resto (`sampleRate` = 1 o 0.05, para poder reescalar). |
| `web_vital_measured` | Una emisión por métrica y carga de página (las métricas finales `INP`/`CLS` se envían al ocultarse la página, con `sendBeacon`). |
| `api_unhandled_error_raised` | Deduplicación por `fingerprint`: máximo 1 evento por huella y minuto, con el número de repeticiones agregado en el procesador. |
| `frontend_error_captured` | Máximo 20 eventos por sesión y 1 por `fingerprint` cada 60 s, para no inundar si un error se repite en bucle. |
| `network_request_failed` | Máximo 1 evento por `routeTemplate` cada 30 s y 10 por sesión. |
| `flow_started` | Una emisión por instancia (`flowInstanceId` nuevo cada vez que el formulario vuelve a estado limpio). |
| `flow_completed` | Una emisión por instancia. |

### 7.3 Flujo técnico

1. **Emisión:** `emit(event_type, properties)` construye el envelope, valida contra el esquema y deja el evento en una cola en memoria acotada (1 000 eventos; si se llena, descarta los más antiguos y lo cuenta). Una tarea en segundo plano la vacía en lotes. Nunca bloquea ni lanza al código de negocio.
2. **Frontend → API:** `track()` acumula eventos y los envía cada 5 s, al llegar a 10 eventos o al ocultarse la página (`navigator.sendBeacon`) a `POST /telemetry/events`: lote de hasta 20 eventos y 32 KB, validado con los mismos esquemas, aceptado también sin sesión (los eventos anteriores al login) pero con límite de frecuencia por origen.
3. **Almacén:** tabla `telemetry_events` en Postgres (Supabase): `event_id uuid` (clave primaria, `ON CONFLICT DO NOTHING` para deduplicar), `occurred_at`, `received_at default now()`, `session_id`, `user_id`, `event_type`, `schema_version`, `request_id`, `source`, `properties jsonb`; índices por (`event_type`, `occurred_at`) y (`user_id`, `occurred_at`); partición mensual.
4. **Procesado:** *stream* = reglas de §7.1 evaluadas sobre las inserciones; *batch* = vistas/consultas agregadas por hora y por día según la tabla anterior.

### 7.4 Volumen y coste (estimación con supuestos a validar con operaciones)

Supuestos: 14 restaurantes, unos 40 usuarios activos al día en el backoffice, ~20 000 peticiones de API al día.

| Fuente | Eventos / día (orden de magnitud) |
|---|--:|
| Órdenes de inventario y derivados (`outbound/inbound_order_created`, `flow_*`) | 1 500 |
| Navegación (`navigation_section_viewed`) | 1 000 |
| `api_latency_recorded` con muestreo (100 % de lentas/5xx + 5 % del resto) | 1 200 |
| `web_vital_measured` (≈ 5 por carga de página) | 2 000 |
| Resto de eventos (incidencias, auth, errores, snapshots) | 500 |
| **Total** | **≈ 6 000** |

Con ≈ 400 bytes por evento son **unos 2,5 MB al día (< 1 GB al año)**: el coste de almacenamiento es irrelevante; lo que justifica el muestreo y el *debounce* es evitar ruido y no inundar el análisis, no el espacio.

## 8. Riesgos y exclusiones

### 8.1 Eventos considerados y descartados

| Evento / dato descartado | Por qué se descarta |
|---|---|
| Clics, movimientos de ratón, mapas de calor y grabación de sesión | Ninguna decisión del equipo depende de ellos y exigirían capturar contenido de pantalla (datos de clientes en incidencias, datos de contacto en perfiles). |
| Tiempos entre pulsaciones y valores de cada campo | Captura de datos personales sin hipótesis que lo justifique; basta con `fieldsTouchedCount`. |
| `ingredient_viewed` / `product_list_viewed` por cada visita | El interés por la sección ya lo da `navigation_section_viewed`, y el estado del stock lo da `stock_snapshot_recorded`; un evento por visita sería volumen sin decisión nueva. |
| `password_changed`, `user_deleted`, cambios de rol | Son acciones de seguridad que deben ir a un **registro de auditoría** inmutable (quién, qué, cuándo), con otro tratamiento y retención; no son analítica de producto. |
| `incident_viewed` (apertura del detalle) | No alimenta ninguna decisión; el ciclo de vida se mide con `incident_created` y `incident_status_changed`. |
| `supplier_status_changed` y alta/baja de proveedores | Cambios muy poco frecuentes; se pueden añadir como *minor* si aparece una hipótesis (hoy `supplier_rate_updated` cubre la pregunta de auditoría). |
| `cache_hit` / `cache_miss` como eventos propios | Ya están en `api_latency_recorded.cache`; duplicarlos multiplicaría el volumen. |
| Dirección IP en claro, geolocalización y huella del dispositivo | Datos personales sin hipótesis de negocio; `sourceKey` basta para detectar ataques el mismo día. |
| SDK de analítica de terceros (GA, Mixpanel, etc.) | Sacaría datos operativos y de usuarios a un tercero sin decisión previa de privacidad y consentimiento. |
| Texto libre: motivo de la salida, proveedor de la entrada, título/descripción de incidencias, mensajes de error | Pueden contener nombres, teléfonos o datos de clientes; solo se captura su existencia (`reasonProvided`, `supplierProvided`) o una causa normalizada. |

### 8.2 Datos que no se van a capturar por privacidad o coste

- **Privacidad:** todo lo de §6.1 (punto 2). Además, los valores de cualquier campo de formulario y el contenido de los CSV de incidencias.
- **Coste / complejidad:** muestreo del 5 % en `api_latency_recorded` (no se guarda el 95 % de las peticiones rápidas y correctas); sin *replay* de sesión; sin trazas distribuidas completas (`requestId` basta para correlacionar en esta etapa).

### 8.3 Riesgos y mitigaciones

| Riesgo | Efecto | Mitigación |
|---|---|---|
| Un desarrollador añade una propiedad con datos personales | Fuga accidental | Esquema con `additionalProperties: false`, validación en el emisor, test de contrato en CI y PR con etiqueta `telemetry-schema` (§6.1, §9.4). |
| Los eventos del frontend se pierden (bloqueadores, cierre de pestaña, red) | Subestimación de navegación, abandono y errores de JS | Tratar las cifras del frontend como **cota inferior**; `sendBeacon` al ocultar la página; las cifras de volumen de negocio salen siempre de eventos de servidor. |
| Reloj del cliente desfasado | Orden de eventos incorrecto | `received_at` en el almacén y marca de sospechoso a más de 5 min de diferencia. |
| Doble recuento entre eventos de servidor y de frontend (`outbound_order_created` frente a `flow_completed`) | Cifras contradictorias | El servidor es la fuente de verdad de **volúmenes**; el frontend solo mide **experiencia** (tiempos, intentos); documentado en cada evento. |
| La telemetría cae o se ralentiza | Afecta al usuario | Emisión asíncrona con cola acotada, sin excepciones hacia el código de negocio; si falla, se descarta y se cuenta. |
| Fatiga de alertas (*stream*) | Se ignoran los avisos | Umbrales de §7.1, agrupación por huella y revisión a los 30 días. |
| Un umbral global (10/30) no sirve igual para todos los insumos | Alertas poco útiles | `thresholdValue` y `level` van en el evento y `stock_snapshot_recorded` da el histórico para fijar umbrales por insumo (decisión abierta nº 1). |
| Entrada ambigua: `supplier` es texto libre | No se puede medir al proveedor | Se captura solo `supplierProvided` y se propone enlazar con el directorio (decisión abierta nº 3). |
| Estado en memoria con varios *workers* del servidor | Contadores inconsistentes | La detección de cruce de umbral es **sin estado** (usa `stockBefore` y `stockAfter` del propio evento); los contadores de alertas se calculan en el almacén, no en cada proceso. |

## 9. Guía de implementación

### 9.1 Orden de entrega recomendado (un PR por paso)

1. **Contrato y base:** cargar `event-schemas.json`, módulo `services/api/app/telemetry/` (`emit`, construcción del envelope, validación, cola), middleware con `X-Request-ID` y `X-Session-Id`, tabla `telemetry_events`, endpoint `POST /telemetry/events` y variable `TELEMETRY_HMAC_KEY`.
2. **Obligatorios del backend:** `outbound_order_created`, `inventory_validation_failed`, `direct_stock_edit_rejected` (incluye el handler de 405), `stock_threshold_triggered` (incluye mover los umbrales a configuración del servidor) y `login_failed`.
3. **Cliente y obligatorios del frontend:** `lib/telemetry.ts` (`track`, cola, `sendBeacon`), cabeceras en `apiFetch`, `useTrackSectionView` y `useFlowTracking`; eventos `navigation_section_viewed`, `flow_abandoned`, `flow_started`, `flow_completed`.
4. **Alertas en *stream*** (§7.1) y vistas por hora y por día.
5. **Resto de oportunidades**, agrupadas por categoría, empezando por errores y autenticación.

### 9.2 Backend

- Los handlers de `main.py` (`RequestValidationError` y el `unhandled_exception_handler`) son los puntos de captura de errores; cada uno decide entre `request_validation_failed`, `inventory_validation_failed` y `direct_stock_edit_rejected` según la ruta (reglas en §5, sin duplicar eventos).
- `create_product` necesita `current_user=Depends(get_current_user)` como parámetro para conocer al creador (FastAPI reutiliza la dependencia del router, sin decodificar el token dos veces).
- Los eventos de orden se emiten **después** de `commit()`: si la transacción falla, no hay evento.
- El `routeTemplate` se obtiene de `request.scope["route"].path`, nunca de `request.url.path`.

### 9.3 Frontend

- `useTrackSectionView(section)` se invoca en cada `app/**/page.tsx` una vez autorizada la sesión; en la home, las secciones diferidas emiten cuando se hacen visibles (callback de `DeferUntilVisible` si el PR #12 ya está fusionado).
- `useFlowTracking(flow)` devuelve `{ markEdited, markSubmitRejected, markCompleted }` y gestiona `flowInstanceId`, el abandono (`pagehide`, cambio de ruta, 10 minutos sin actividad) y `session_expired`.
- `apiFetch` añade `X-Request-ID` y `X-Session-Id` y emite `network_request_failed` y `session_expired`.
- Añadir `app/error.tsx` y los listeners globales para `frontend_error_captured`, y `useReportWebVitals` para `web_vital_measured`.

### 9.4 Pruebas y criterio de «hecho» por evento

1. **Test de contrato:** un test carga `event-schemas.json` y valida que cada evento emitido en las pruebas de integración cumple su esquema (y que una propiedad fuera de la allowlist es rechazada).
2. El evento se emite **exactamente una vez** por suceso y **ninguna** en las ramas en las que este documento dice que no se emite (p. ej. un cambio de estado sin efecto; un `insufficient_stock` no genera además `request_validation_failed`).
3. Un test comprueba que ningún valor de la lista prohibida (§6.1) aparece en las propiedades de eventos generados con datos de prueba que contienen emails, nombres y texto libre.
4. El evento llega con `requestId` igual al de la cabecera de respuesta de la misma petición.

### 9.5 Decisiones abiertas para la revisión del viernes

| Nº | Decisión | Mi propuesta |
|--:|---|---|
| 1 | Umbrales de stock: ¿globales (10/30) o por insumo o restaurante? | v1 global en configuración del servidor; revisar con `stock_snapshot_recorded` tras 30 días. |
| 2 | ¿Se cierra el registro público (`POST /users`)? | Decidir con los datos de `user_registered` tras 2 semanas. |
| 3 | Enlazar `supplier` de las entradas con el directorio de proveedores | Sí, como cambio previo a medir fiabilidad de proveedores. |
| 4 | Dónde se almacena: tabla en Supabase o servicio externo | Tabla en Supabase (ya está en el stack y evita sacar datos a un tercero). |
| 5 | Retención de eventos y política de baja de usuarios | §6.3: 13 meses y reescritura de `userId` a `deleted`. |
| 6 | Canal de avisos del *stream* (correo, mensajería, SMS) | Correo en la v1; el destinatario por restaurante sale de una lista de configuración. |
| 7 | ¿Hace falta aviso/consentimiento a los usuarios del backoffice? | Consultarlo con quien lleve legal/privacidad antes de producción: el plan trata `userId` como dato personal seudonimizado. |

## 10. Trazabilidad con los criterios de evaluación

| Criterio | Dónde se cumple |
|---|---|
| Métricas obligatorias presentes e identificadas | §1.1 (origen y mapeo) y eventos marcados *obligatorio* en §4 y §5 |
| Cobertura técnica **y** de negocio, amplia | §4: 7 categorías, 24 oportunidades adicionales (técnicas: rendimiento, errores, autenticación, navegación; negocio: inventario, incidencias, proveedores) |
| Cada evento con hipótesis y decisión | §5: frase de oro por evento; ninguno «por si acaso» |
| Envelope consistente | §3 y `definitions.envelope` en el JSON (todos los eventos incluyen los 8 campos obligatorios, más `source`) |
| Allowlist por evento | §5 (tabla de propiedades) y `additionalProperties: false` en el JSON |
| `event-schemas.json` válido y consistente con el plan | JSON Schema draft-07; el catálogo y el JSON se generaron de la misma fuente y se validaron (esquema, un ejemplo válido de cada evento y casos inválidos) |
| Stream/batch justificado por urgencia | §7 |
| Datos sensibles identificados con su tratamiento | §6.2 |
| Riesgos y exclusiones con pensamiento crítico | §8 |
| Suficientemente preciso para implementar sin preguntar | §5 (dónde se emite, cuándo no) y §9 (orden, pruebas, decisiones abiertas) |

## Revisión 1.1.0 (captura en el frontend)

Al implementar la captura (`feat: telemetry event capture`) se detectó que varios eventos obligatorios estaban definidos solo con origen `backend`, pero el ticket exige capturarlos desde el backoffice. Cambios (compatibles: *minor*, salvo el enum ampliado de `login_failed`, aditivo):

- **`source` admite `frontend`** además del original en 11 eventos: `outbound_order_created`, `inventory_validation_failed`, `stock_threshold_triggered`, `direct_stock_edit_rejected`, `login_failed`, `login_succeeded`, `incident_created`, `incident_status_changed`, `incident_csv_analyzed`, `user_registered`, `api_latency_recorded`. Son observaciones del cliente sobre una respuesta de la API; al consolidar se deduplican por (`event_type`, `requestId`) y manda la versión `backend`.
- **`login_failed` (frontend):** `failureReason` suma `invalid_credentials` (401), `network_error` (sin respuesta) y `server_error` (otro estado). `accountKey` y `sourceKey` pasan a opcionales: el navegador no los conoce y **nunca** envía email, contraseña ni IP.
- **`api_latency_recorded.cache`** pasa a opcional (el cliente solo lo sabe si la API devuelve `X-Cache`).
- **`sessionId`:** el cliente lo genera al iniciar sesión y lo guarda en memoria/`sessionStorage`; antes del login se usa un identificador anónimo efímero.


## Almacenamiento (`feat: telemetry event storage`)

Los eventos validados se guardan en la tabla `telemetry_events` de Supabase (`services/api/migrations/001_create_telemetry_events.sql`). Es una tabla de **solo escritura**: no hay UPDATE ni DELETE en el código y un trigger los bloquea en la base de datos.

| Columna | Tipo | Origen en el envelope |
|---|---|---|
| `id` | BIGSERIAL, PK | generado |
| `event_id` | UUID, UNIQUE | `eventId` (un reintento no duplica el hecho) |
| `event_type` | TEXT | `event_type` |
| `timestamp` | TIMESTAMPTZ | `timestamp` |
| `service` | TEXT | `source` (`backend`, `frontend`, `job`) |
| `user_id` | TEXT | `userId` |
| `session_id` | TEXT | `sessionId` |
| `tags` | JSONB | `properties`, solo las claves de la allowlist del evento |

Índices: `timestamp`, `event_type` y GIN sobre `tags`.

**Dimensiones de Brasaland en `tags`.** `tags` es el `properties` completo, así que conserva las dimensiones específicas del dominio: `restaurant` (los 14 restaurantes: `outbound_order_created`, `inbound_order_created`, `inventory_validation_failed`, `stock_threshold_triggered`, `ingredient_created`, `stock_snapshot_recorded`) y `branch` (la sede o `central`: `incident_created`), además de `ingredientId`, `category`, `origin` y `section`/`flow` en navegación. Ejemplo: `tags @> '{"restaurant": "Brasaland Laureles"}'` usa el índice GIN.

**Qué se guarda y qué se rechaza.** El endpoint valida cada evento con `TelemetryEvent` (envelope) y con la allowlist de este plan: un evento con envelope inválido, `event_type` fuera del catálogo o sin sus propiedades obligatorias se rechaza **individualmente** (no cancela el lote); las claves fuera de la allowlist se descartan y nunca se guardan. `requestId` y `schemaVersion` se validan pero no tienen columna (no se guardan). Un `eventId` ya guardado cuenta como rechazado.
