# Auditoría de serialización de la API

Alcance: `services/api` (FastAPI). Criterio: cada endpoint declara un `response_model` explícito e independiente del esquema de entrada y del registro interno, y expone solo los campos que su consumidor lee.

Estado final: **todos los endpoints ✅** (ver "Resultado"). Esta tabla conserva el estado **inicial** de cada uno para dejar trazabilidad de lo que se cambió y por qué.

Leyenda: ✅ ya serializado · ⚠️ parcialmente serializado · ❌ sin serializar.

## 1. Metodología

Para cada endpoint se respondió: qué recibe, qué devolvía realmente y qué debería devolver, mirando qué campos lee el frontend (`uis/backoffice`) y no qué columnas tiene el modelo.

Hallazgo general: **ningún endpoint devolvía un objeto ORM en crudo ni `hashed_password`**. El código ya mapeaba a modelos Pydantic. Los problemas reales eran otros: esquemas de salida que heredaban del de entrada, claves de almacenamiento expuestas (`id` del documento, `user_id`), el email repetido en el registro, un listado que devolvía texto largo que la tabla no muestra y un endpoint que devolvía un `dict` sin tipar.

## 2. Autenticación (primer bloque, mayor riesgo)

| Endpoint | Propósito | Antes | Estado inicial | Después |
|---|---|---|---|---|
| `POST /auth/login` | Obtener token | `TokenResponse` (`access_token`, `token_type`) | ✅ salida. ⚠️ entrada: `email` y `username` opcionales, sin ninguno se autenticaba contra la cadena `"none"` | Salida igual. La entrada exige uno de los dos (400 si faltan) |
| `GET /auth/me` | Perfil del llamante | `MeResponse` con `profile` = `ProfileResponse` (`id`, `user_id`, `name`, `phone`, `address`) | ⚠️ expone el id del documento y la clave foránea `user_id` | `profile` = `ProfilePublic` (`name`, `phone`, `address`). `email` y `role` se mantienen: la vista de perfil depende de ellos |
| `POST /auth/forgot-password` | Solicitar enlace | `MessageResponse`, mensaje idéntico exista o no el email | ✅ | Sin cambios (no enumera cuentas) |
| `POST /auth/reset-password` | Fijar nueva contraseña | `MessageResponse` | ✅ | Sin cambios |
| `POST /auth/change-password` | Cambiar contraseña | `MessageResponse` | ✅ | Sin cambios |
| `POST /users` (registro) | Crear cuenta | `UserResponse` (`id`, `email`, `is_active`, `role`, `created_at`) | ⚠️ repite el email que ya viaja en la petición y devuelve campos que el cliente no usa (el formulario ignora la respuesta y hace login) | `RegisterResponse` (`id`, `message`) |

## 3. Usuarios y perfiles

| Endpoint | Propósito | Estado inicial | Después |
|---|---|---|---|
| `GET /users` | Listado (solo admin) | ⚠️ reutilizaba el esquema de detalle | `UserListItem` (`id`, `email`, `role`, `is_active`), sin timestamps de auditoría |
| `GET /users/{id}` | Detalle (self o admin) | ✅ `UserResponse`, lista explícita de campos seguros | Sin cambios |
| `PUT /users/{id}` | Actualizar | ✅ salida. ⚠️ entrada: `is_active` aceptado de cualquier usuario sobre sí mismo | Salida igual. `is_active` pasa a requerir admin, igual que `role` |
| `DELETE /users/{id}` | Borrar | ✅ 204 sin cuerpo | Sin cambios |
| `GET /profiles/me` | Mi perfil | ⚠️ `ProfileResponse` con `id` y `user_id` | `ProfilePublic` (`name`, `phone`, `address`) |
| `PUT /profiles/me` | Editar mi perfil | ⚠️ ídem | `ProfilePublic`. La entrada `ProfileUpdate` ya era un esquema aparte (`extra="forbid"`) |

Decisión sobre relaciones: el perfil se devuelve **plano y sin claves**, no anidado. Se consulta siempre como "el mío", así que `user_id` no aporta nada al cliente.

## 4. Proveedores

Se monta dos veces (`/api/suppliers` y el alias `/suppliers`); los 8 endpoints de cada montaje comparten el mismo esquema.

| Endpoint | Propósito | Estado inicial | Después |
|---|---|---|---|
| `GET ""`, `GET /country/{c}`, `GET /category/{c}` | Listados | ⚠️ `Supplier`, que **hereda de `SupplierBase`** (el esquema de entrada con `extra="forbid"` y alias de validación) | `list[SupplierResponse]` |
| `GET /{id}` | Detalle | ⚠️ ídem | `SupplierResponse` |
| `POST ""` | Crear | ⚠️ ídem. La entrada `SupplierCreate` ya estaba separada | `SupplierResponse` |
| `PATCH /{id}/rate`, `PATCH /{id}/status` | Actualizar tarifa/estado | ⚠️ ídem. Entradas `RateUpdate`/`StatusUpdate` ya separadas | `SupplierResponse` |
| `DELETE /{id}` | Borrar | ✅ 204 | Sin cambios |

`SupplierResponse` lista cada campo (`id`, `name`, `categories`, `country`, `rate`, `status`, `updated_at`). Detalle y listado **comparten esquema** porque el directorio del backoffice lee exactamente esos siete campos en la tabla, así que no hay una proyección más ligera que encaje con el consumidor.

## 5. Incidencias

| Endpoint | Propósito | Estado inicial | Después |
|---|---|---|---|
| `POST /api/incidents` | Crear | ⚠️ `Incident`, que hereda de `IncidentBase` (esquema de entrada) | `IncidentResponse` |
| `GET /api/incidents` | Listado con filtros | ⚠️ devolvía el objeto completo, incluida `description` (texto largo) y timestamps, que la tabla no muestra | `list[IncidentListItem]` (`id`, `title`, `category`, `origin`, `branch`, `status`) |
| `GET /api/incidents/{id}` | Detalle | ⚠️ ídem creación | `IncidentResponse` (detalle completo) |
| `PATCH /api/incidents/{id}/status` | Cambiar estado | ⚠️ ídem. La entrada `StatusUpdate` ya estaba separada | `IncidentResponse` |
| `GET /api/incidents/summary` | Agregados | ✅ `IncidentSummary` | Sin cambios |
| `POST /api/incidents/analyze` | Analizar CSV subido | ❌ `-> dict[str, object]`, sin `response_model`, contrato solo implícito | `AnalysisResponse` tipado, mismos 7 campos |
| `GET /api/incidents/results/export` | Descargar CSV | ⚠️ `StreamingResponse` sin documentar en OpenAPI | Sigue siendo CSV (no es JSON). Se declara `response_class` y `text/csv` en `/docs` |

Decisión sobre listado vs. detalle: el listado **no reutiliza** el esquema de detalle. Se eligió quitar `description` y los timestamps porque la tabla del backoffice solo lee seis campos; el detalle completo se pide por id.

## 6. Inventario (Supabase / SQLModel)

Era el módulo mejor resuelto: ya tenía `schemas.py` independiente de los modelos ORM y mapeaba cada fila a mano.

| Endpoint | Propósito | Estado inicial | Después |
|---|---|---|---|
| `GET /inventory/products` | Listado con stock | ✅ `IngredientResponse` | Sin cambios |
| `POST /inventory/products` | Crear insumo | ✅ | Sin cambios |
| `GET /inventory/products/{id}` | Detalle | ✅ | Sin cambios |
| `POST /inventory/orders/inbound` | Registrar entrada | ✅ `IngredientEntryResponse` | Sin cambios |
| `POST /inventory/orders/outbound` | Registrar salida | ✅ `IngredientExitResponse` | Sin cambios |
| `GET /inventory/orders` | Entradas y salidas | ⚠️ `type: str` sin restringir | `type: Literal["inbound", "outbound"]`, el contrato queda cerrado |

**`user_uuid` se mantiene a propósito.** Es un id interno, pero la tabla de órdenes del backoffice lo muestra en la columna "Creada por". Quitarlo rompería esa pantalla. Alternativa a futuro: exponer el nombre visible del usuario en lugar del id.

## 7. Resultado

| Estado | Inicial | Final |
|---|---|---|
| ✅ Ya serializado | 12 | **33** |
| ⚠️ Parcial | 20 | 0 |
| ❌ Sin serializar | 1 | 0 |

(33 endpoints lógicos; el alias `/suppliers` duplica los 8 de proveedores en OpenAPI.)

Ver la lista final por endpoint en las secciones 2 a 6, columna "Después".

## 8. Verificación

- Tests existentes: 42 pasaban antes de tocar nada. Un test se actualizó a propósito (`test_register_happy_path...`): exigía que el registro devolviera el email, justo lo que el briefing prohíbe.
- Tests nuevos en `tests/test_serialization.py` (11): forma exacta de cada respuesta cambiada, `is_active` solo para admin, login sin identificador, y dos guardas generales sobre OpenAPI (toda respuesta JSON 2xx referencia un modelo; ningún esquema de salida contiene `hashed_password`, `token_hash` ni contraseñas). Contra el código anterior, **7 de los 11 fallan**; con los cambios, **53/53 pasan**.
- Prueba manual con un servidor real (`uvicorn`) y `curl`: registro, `/auth/me`, `/profiles/me`, proveedores, incidencias (crear y listar), inventario (crear insumo, entrada, listar órdenes), `/analyze` con `data/raw/incidents-COMPANY.csv` (100 procesadas, 90 válidas, 10 inválidas) y `/api/incidents/results/export` (200, `text/csv`). `/docs` responde 200.
- El frontend no necesita cambios: el formulario de registro ignora el cuerpo de la respuesta, la tabla de incidencias lee solo los seis campos del listado y el formulario de perfil ya tipaba `{ name, phone, address }`.

## 9. Observaciones fuera de alcance

No se tocaron porque no son de serialización:

- `PUT /users/{id}` permite cambiar el email sin confirmar la contraseña actual.
- El montaje duplicado `/suppliers` y `/api/suppliers` genera operaciones repetidas en `/docs`.
- `IngredientCreate` acepta `name`, `sku` y `restaurant` vacíos.
