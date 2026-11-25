# Audit log

Responde a **quién hizo qué, sobre qué recurso, cuándo y desde dónde**, y permite demostrar que nadie lo ha reescrito después.
No es el log técnico (errores, latencia): ese sigue en `brasaland.*` / `uvicorn`.

## Esquema de una entrada

Almacén: `audit_log.jsonl` (una línea JSON por entrada, solo se añade) + `audit_head.json` (cabeza firmada). Fuera de git.

| Campo | Qué es |
| --- | --- |
| `seq` | nº correlativo (1, 2, 3…) |
| `id`, `timestamp` | UUID y fecha UTC de la acción |
| `actor_type` | `user` persona · `agent` agente de IA · `system` proceso (worker, tarea) · `anonymous` sin identificar (login fallido) |
| `actor_id`, `actor_label`, `actor_role`, `actor_department` | quién (id, correo, rol y departamento **en ese momento**). En `anonymous`, `actor_id` es una huella del correo intentado |
| `action` | `supplier.rate_change`, `user.assignment_change`, `auth.login`… (lista abajo) |
| `category` | `auth` · `access` · `federated` · `audit` · `process` (eventos de **seguridad**) · `data` (negocio) |
| `resource_type`, `resource_id` | sobre qué |
| `department` | departamento dueño del recurso (reparte la visibilidad) |
| `outcome` | `success` · `failure` · `denied` (403) |
| `origin`, `channel` | IP del cliente (`http`) o `process:<nombre>:<pid>` (`process`) |
| `details` | antes/después de un cambio, proveedor, ruta, estado HTTP. **Nunca** contraseñas, tokens ni `code` de OAuth |
| `prev_hash`, `hash` | enlace de la cadena (ver más abajo) |

## Acciones instrumentadas (inventario)

Fuente única: `app/audit/catalog.py`. Un test (`test_toda_ruta_que_modifica_datos_esta_inventariada`) **falla** si alguien añade una ruta que modifica datos sin inventariarla.

| Área | Acciones |
| --- | --- |
| Sesiones | `auth.login` (éxito y fallo), `auth.register`, `auth.password_reset_request`, `auth.password_reset`, `auth.password_change` |
| Cuentas externas | `federated.link_start`, `federated.link`, `federated.unlink`, `federated.login_start`, `federated.login` (éxito y rechazo) |
| Permisos | `user.create`, `user.update`, `user.delete`, `user.assignment_change` (rol y departamento, antes → después), `profile.update`, `role.create/update`, `department.create/update` |
| Proveedores | `supplier.create`, `supplier.rate_change` (antes → después), `supplier.status_change`, `supplier.delete` (rutas `/api/suppliers` y `/suppliers`) |
| Operaciones | `incident.create`, `incident.status_change`, `incident.analyze`, **`incident.export`** (salida de datos), `inventory.product_create/inbound/outbound`, `reporting.run` |
| Compras/RFP | `rfp.ticket_create`, `rfp.approval_start/retry/decision`, `rfp.generate`, `rfp.reprocess` |
| Reportes internos | `internal_report.create/update/delete/approve` |
| Agente y plataforma | `agent.query`, `knowledge.query`, `telemetry.ingest` |
| Procesos | `process.task` (tareas de Celery: éxito y fallo) |
| Denegaciones | `access.denied`: **todo 403 de cualquier ruta**, aunque no esté en el inventario (p. ej. un `GET` de datos ajenos) |
| El propio visor | `audit.view`, `audit.verify` (quién consulta el log queda registrado) |

La instrumentación es un **middleware** (`app/audit/middleware.py`), no código repartido por cada ruta: no hay que acordarse de auditar. Los manejadores solo aportan lo que el middleware no puede saber (`note(...)`: antes/después de un cambio, quién acaba de iniciar sesión).

## Personas, agentes y procesos

- **Persona** (`user`) y **agente** (`agent`) son cuentas distintas: `account_type` lo fija un Admin en el servidor al crear la cuenta (`POST /users`, o la semilla `agente.operaciones@…`). El cliente no puede declararse agente ni persona (hay un test con cabeceras falsas).
- **Proceso** (`system`): los workers escriben en el mismo registro con `record_process` (`services/async_tasks/audit.py`), canal `process` y origen `process:<nombre>:<pid>`.
- **Sin identificar** (`anonymous`): login fallido o petición sin sesión. Se guarda el correo intentado (no la contraseña).

## Inmutabilidad (qué impide editar o borrar)

1. `AuditLog` solo tiene `append`, `iter_entries`, `query`, `facets` y `verify`. **No existe** `update`, `delete` ni `truncate` (un test lo fija).
2. La API del registro solo tiene `GET` (`/audit-log`, `/audit-log/facets`, `/audit-log/verify`). `POST/PUT/PATCH/DELETE` → 404/405 (test sobre el OpenAPI).
3. El fichero se abre con `O_APPEND`; la escritura es atómica y exclusiva (`flock`) entre procesos (API y workers), con `fsync`.
4. Si el final del fichero no se puede leer, **se rechaza escribir encima** (no se oculta una alteración con entradas nuevas).

## Evidencia de alteración (tamper-evidence)

- Cada entrada: `hash = HMAC-SHA256(clave, prev_hash | contenido canónico)`. Editar, borrar o reordenar rompe la cadena **desde ese punto**.
- Con HMAC, quien tenga el fichero pero **no la clave** no puede recalcular una cadena válida (test `test_sin_la_clave_no_se_puede_forjar_una_cadena_valida`).
- `audit_head.json` guarda `(seq, hash)` de la última entrada firmado con la misma clave: detecta que recorten el final o vacíen el fichero.
- `GET /audit-log/verify` recorre toda la cadena y devuelve la primera entrada rota y el motivo. Salida real de la demo: [`evidence/audit-log-alteracion.txt`](evidence/audit-log-alteracion.txt).

**Límite honesto:** quien controle el servidor **y** la clave (`AUDIT_CHAIN_KEY`) puede reescribirlo todo. Para ese caso: guardar la clave fuera del servidor de datos y **anclar** el `head_hash` fuera (export semanal a almacenamiento WORM o a un correo interno). Es una decisión de despliegue, no de código; queda como recomendación al CTO.

## Visor y alcance («no todo Admin ve todo»)

Backoffice `/admin/audit` (menú «Auditoría» para Supervisor+). Filtros: actor, tipo de actor, acción, recurso, categoría, resultado, rango de fechas. Paginación por cursor (`limit` ≤ 200, `before_seq`).

| Quién | Qué ve |
| --- | --- |
| Empleado | nada (403) |
| Supervisor o Admin de un departamento | **solo acciones sobre datos de negocio de su departamento** (`category=data` del suyo). No ve inicios de sesión, cambios de permisos, cuentas externas ni procesos |
| Admin de Tecnología | todo, incluidos los eventos de seguridad; es el único que puede **verificar la integridad** |
| Sin departamento asignado | 403 hasta que un Admin se lo asigne |

El alcance se aplica **en el servidor**, antes de filtrar y contar (`total`, las facetas y la paginación nunca revelan entradas fuera de alcance). Un filtro `?department=` no amplía el alcance (test). La decisión por rango vive en `app/access/permissions.py` (único punto de decisión de acceso).

> **Supuesto a confirmar con el briefing de la empresa** (no llegó adjunto): qué departamento ve qué categoría. Ajustar solo cambia `app/audit/scope.py`.

## Límites conocidos

- Almacén en fichero (JSON Lines), coherente con el resto de la API (TinyDB). `query` recorre el fichero: válido para el volumen actual; con millones de entradas habría que pasar a una tabla indexada manteniendo la misma cadena.
- Si el registro falla al escribir **después** de que la acción ya se ejecutó, se emite un log `CRITICAL` (la acción no se deshace). Un despliegue estricto puede convertirlo en alerta.
- El visor audita la lectura, pero no guarda el contenido de los filtros usados.
- Los `GET` de lectura normal no se auditan (solo la exportación, las lecturas denegadas y el propio visor): auditar toda lectura inflaría el log y escondería lo importante.
