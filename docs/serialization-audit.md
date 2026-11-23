# Auditoría de serialización de la API

Alcance: `services/api` (FastAPI). Criterio: cada endpoint declara un `response_model` explícito e independiente del esquema de entrada y del registro interno, y expone solo los campos que su consumidor lee.

Estado final: **todos los endpoints ✅** (ver secciones 7 y 10). Esta tabla conserva el estado **inicial** de cada uno para dejar trazabilidad de lo que se cambió y por qué.

Leyenda: ✅ ya serializado · ⚠️ parcialmente serializado · ❌ sin serializar.

## 1. Metodología

Para cada endpoint se respondió: qué recibe, qué devolvía realmente y qué debería devolver, mirando qué campos lee el frontend (`uis/backoffice`) y no qué columnas tiene el modelo.

Hallazgo general: **ningún endpoint devolvía un objeto ORM en crudo ni `hashed_password`**. El código ya mapeaba a modelos Pydantic. Los problemas reales eran otros: esquemas de salida que heredaban del de entrada, claves de almacenamiento expuestas (`id` del documento, `user_id`), el email repetido en el registro, un listado que devolvía texto largo que la tabla no muestra y un endpoint que devolvía un `dict` sin tipar.

## 2. Autenticación (primer bloque, mayor riesgo)

| Endpoint | Propósito | Antes | Estado inicial | Después |
|---|---|---|---|---|
| `POST /auth/login` | Obtener token | `TokenResponse` (`access_token`, `token_type`): el token de acceso es el resultado esperado del login, no un token interno | ✅ salida. ⚠️ entrada: `email` y `username` opcionales, sin ninguno se autenticaba contra la cadena `"none"` | Salida igual. La entrada exige uno de los dos (400 si faltan) |
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
| `DELETE /users/{id}` | Borrar | ✅ 204 sin cuerpo | Sin cambios; ahora con `response_model=None` explícito |
| `GET /profiles/me` | Mi perfil | ⚠️ `ProfileResponse` con `id` y `user_id` | `ProfilePublic` (`name`, `phone`, `address`) |
| `PUT /profiles/me` | Editar mi perfil | ⚠️ ídem | `ProfilePublic`. La entrada `ProfileUpdate` ya era un esquema aparte (`extra="forbid"`) |

Decisión sobre relaciones: el perfil se devuelve **plano y sin claves**, no anidado. Se consulta siempre como "el mío", así que `user_id` no aporta nada al cliente.

## 4. Proveedores

Se monta dos veces: `/api/suppliers` y el alias `/suppliers` (mismas 8 operaciones con otro prefijo). Se listan con el prefijo `/api/suppliers`; el alias comparte los mismos esquemas.

| Endpoint | Propósito | Estado inicial | Después |
|---|---|---|---|
| `GET /api/suppliers` | Listado con filtros `country` y `category` | ⚠️ `Supplier`, que **hereda de `SupplierBase`** (el esquema de entrada con `extra="forbid"` y alias de validación) | `list[SupplierResponse]` |
| `GET /api/suppliers/country/{country}` | Listado por país | ⚠️ ídem | `list[SupplierResponse]` |
| `GET /api/suppliers/category/{category}` | Listado por categoría | ⚠️ ídem | `list[SupplierResponse]` |
| `GET /api/suppliers/{supplier_id}` | Detalle | ⚠️ ídem | `SupplierResponse` |
| `POST /api/suppliers` | Crear | ⚠️ ídem. La entrada `SupplierCreate` ya estaba separada | `SupplierResponse` |
| `PATCH /api/suppliers/{supplier_id}/rate` | Actualizar tarifa | ⚠️ ídem. Entrada `RateUpdate` ya separada | `SupplierResponse` |
| `PATCH /api/suppliers/{supplier_id}/status` | Actualizar estado | ⚠️ ídem. Entrada `StatusUpdate` ya separada | `SupplierResponse` |
| `DELETE /api/suppliers/{supplier_id}` | Borrar | ✅ 204 sin cuerpo | Sin cambios; ahora con `response_model=None` explícito |

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
| `GET /api/incidents/results/export` | Descargar CSV | ⚠️ `StreamingResponse` sin documentar en OpenAPI | Sigue siendo CSV (no es JSON). Se declara `response_class`, `response_model=None` y `text/csv` en `/docs` |

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

**Endpoints sin cuerpo JSON.** Tres operaciones lógicas no devuelven JSON y por eso no tienen esquema de salida: `DELETE /users/{id}` y `DELETE /api/suppliers/{id}` (204, sin cuerpo) y la descarga CSV. Las tres lo declaran con `response_model=None` explícito en el decorador, y un test impide que aparezca otra excepción.

## 8. Verificación

- Tests existentes: 42 pasaban antes de tocar nada. Un test se actualizó a propósito (`test_register_happy_path...`): exigía que el registro devolviera el email, justo lo que el briefing prohíbe.
- Tests nuevos en `tests/test_serialization.py` (12): forma exacta de cada respuesta cambiada, `is_active` solo para admin, login sin identificador, y tres guardas generales (toda respuesta JSON 2xx referencia un modelo en OpenAPI; todas las rutas declaran `response_model` salvo los borrados 204 y el CSV; ningún esquema de salida contiene `hashed_password`, `token_hash` ni contraseñas). Contra el código anterior, **7 de los 12 fallan**; con los cambios, **54/54 pasan**.
- Prueba manual con un servidor real (`uvicorn`) y `curl`: registro, `/auth/me`, `/profiles/me`, proveedores, incidencias (crear y listar), inventario (crear insumo, entrada, listar órdenes), `/analyze` con `data/raw/incidents-COMPANY.csv` (100 procesadas, 90 válidas, 10 inválidas) y `/api/incidents/results/export` (200, `text/csv`). `/docs` responde 200.
- El frontend no necesita cambios: el formulario de registro ignora el cuerpo de la respuesta, la tabla de incidencias lee solo los seis campos del listado y el formulario de perfil ya tipaba `{ name, phone, address }`.

## 9. Cambios aplicados

Esquemas nuevos (todos de salida, independientes de los de entrada):

| Esquema | Módulo | Sustituye a |
|---|---|---|
| `ProfilePublic` | `app/auth/models.py` | `ProfileResponse` (con `id` y `user_id`) en `/auth/me` y `/profiles/me` |
| `RegisterResponse` | `app/auth/models.py` | `UserResponse` en `POST /users` |
| `UserListItem` | `app/auth/models.py` | `UserResponse` en `GET /users` |
| `SupplierResponse` | `app/suppliers/models.py` | `Supplier` (modelo interno que heredaba de la entrada) |
| `IncidentResponse` | `app/incidents/models.py` | `Incident` en crear, detalle y cambio de estado |
| `IncidentListItem` | `app/incidents/models.py` | `Incident` en el listado |
| `AnalysisResponse` | `app/incidents/models.py` | `dict[str, object]` en `/analyze` |

Otros cambios:

- `OrderResponse.type` pasa de `str` a `Literal["inbound", "outbound"]`.
- Endurecimiento de escrituras: `is_active` en `PUT /users/{id}` requiere admin; `POST /auth/login` exige `email` o `username`.
- `response_model=None` explícito en los dos borrados 204 y en la descarga CSV.
- `tests/test_register.py`: el test dejó de exigir el email en la respuesta del registro.

## 10. Cumplimiento de los criterios de evaluación

| Criterio | Cómo se cumple |
|---|---|
| Cada endpoint tiene un `response_model` explícito | 37 de 41 operaciones (30 de 33 lógicas) lo declaran con un esquema; las tres sin cuerpo JSON lo declaran como `None`. Test: `test_every_route_declares_an_explicit_response_model_or_has_no_body` |
| Esquemas de entrada y salida separados | Ninguna respuesta hereda de un esquema de entrada (`SupplierResponse` e `IncidentResponse` dejaron de heredar de `SupplierBase`/`IncidentBase`) |
| Listados solo con los campos necesarios | `GET /api/incidents` (6 campos, sin `description` ni timestamps) y `GET /users` (4 campos). Proveedores e inventario comparten esquema con el detalle porque el cliente lee todos sus campos (secciones 4 y 6) |
| Sin contraseñas hasheadas ni tokens internos; los flujos sin sesión no reenvían el email | Registro devuelve `id` y `message`; forgot/reset devuelven un mensaje genérico; login devuelve el token de acceso. Solo `GET /auth/me` devuelve el email. Test: `test_no_output_schema_exposes_credential_fields` |
| Documento de auditoría con todos los endpoints, estado original y cambios | Este archivo: secciones 2 a 6 (estado original y final por endpoint) y sección 9 (cambios) |
| La aplicación sigue funcionando | 42 tests previos sin cambios de comportamiento salvo el del registro, más 12 nuevos; prueba manual contra un servidor real (sección 8) |

## 11. Observaciones fuera de alcance

No se tocaron porque no son de serialización:

- `PUT /users/{id}` permite cambiar el email sin confirmar la contraseña actual.
- El montaje duplicado `/suppliers` y `/api/suppliers` genera operaciones repetidas en `/docs`.
- `IngredientCreate` acepta `name`, `sku` y `restaurant` vacíos.
