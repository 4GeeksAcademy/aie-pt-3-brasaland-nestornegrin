# Roles y permisos (RBAC con dos ejes)

Ticket abierto por el CTO (Nicolás Park) tras el aviso de Legal: hasta ahora cualquier usuario autenticado tenía el mismo acceso.
Fuente de verdad de nombres y semillas: `brasaland-BRIEFING.es.md` del ticket.

## Dos ejes independientes

| Eje | Responde a… | Entidad | En el usuario |
| --- | --- | --- | --- |
| **Rol** | ¿qué puede *hacer*? | `roles` (código, nombre, **rango**, capacidades) | `role_id` |
| **Departamento** | ¿qué datos le *competen*? | `departments` (código, nombre, responsable) | `department_id` |

`role_id` y `department_id` son claves separadas: ninguna se deriva de la otra. `PATCH /users/{id}/assignment` solo modifica el campo enviado.
Cambiar el departamento no cambia el rango y viceversa. El Admin sigue perteneciendo a un departamento (`technology`); ver otros departamentos es la capacidad `cross_department` del rol Admin.

## Roles y capacidades (jerarquía estricta: employee < supervisor < admin)

| Rol (`code`) | Rango | Capacidades | En la práctica |
| --- | --- | --- | --- |
| Empleado (`employee`) | 1 | `read`, `create` | Lee y crea registros de **su** departamento |
| Supervisor (`supervisor`) | 2 | + `update`, `approve` | Además actualiza y aprueba en **su** departamento. No elimina, no administra, no ve otros departamentos |
| Admin (`admin`) | 3 | + `delete`, `administer`, `cross_department` | Elimina, administra usuarios/roles/departamentos y ve todos los departamentos |

Al crear o editar un rol, la API valida la jerarquía: un rango mayor debe incluir **todas** las capacidades de los rangos menores y no se admiten rangos repetidos ni capacidades desconocidas.

## Departamentos (alcance de datos)

`restaurant_operations`, `procurement`, `marketing`, `people_culture`, `training_quality`, `technology`.
Un departamento **no concede acciones**: dos Supervisores (Felipe/Operaciones y Lucía/Compras) tienen las mismas capacidades pero no ven los datos del otro.

## Cómo se decide (un único punto)

`services/api/app/access/permissions.py` → `require_access(Action, department)`, una dependencia de FastAPI. Las rutas solo la **declaran**; ninguna compara roles por su cuenta (lo garantiza un test).

1. **Rol primero**: si falta la capacidad → `403` con `X-Access-Denied: insufficient_role` y el rol que hace falta. Nunca un `200` vacío.
2. **Departamento después**: si el dato es de otro departamento y no hay `cross_department` → `403` con `X-Access-Denied: department_scope`.
3. Los **listados** devuelven solo el departamento del llamante (alcance, no denegación silenciosa); `?department=` ajeno → 403.
4. Sin departamento asignado y sin `cross_department` → 403 explícito.

## Matriz de endpoints

| Recurso | Lectura | Creación | Actualizar | Aprobar | Eliminar | Departamento |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /auth/me` | autenticado | | | | | — |
| `/users` (listar/crear), `PATCH /users/{id}/assignment`, `DELETE /users/{id}` | admin | admin | admin | | admin | — |
| `/roles`, `/departments` (GET/POST/PUT) | admin | admin | admin | | | — |
| `/internal-reports` | employee | employee | supervisor | supervisor | admin | el del registro |
| `/api/suppliers` y tarifas | employee | employee | supervisor (tarifa) | supervisor (estado) | admin | `procurement` |
| `/api/incidents` (+ export, summary, analyze) | employee | employee | supervisor (estado) | | | `restaurant_operations` |
| `/inventory/*` y `/reporting/inventory-performance/*` | employee | employee (entradas/salidas) | supervisor | | | `restaurant_operations` |
| `/telemetry/report` | employee | | | | | `technology` |
| `/rfp/*` | employee | employee | supervisor | supervisor del departamento que decide (`/approvals/{dept}`) | | según aprobación |
| Registro público | `POST /auth/register` → siempre `employee` sin departamento | | | | | |

Notas: `POST /users` ya no es público (solo Admin, con `role_id`/`department_id`); el auto‑registro vive en `POST /auth/register`.

## Datos semilla

`python -m app.access.seed` (desde `services/api`) o `SEED_DEMO_DATA=1` al arrancar. Idempotente. Crea los 3 roles, los 6 departamentos, los 5 usuarios del briefing
(`felipe.ops`, `lucia.procurement`, `camila.marketing`, `jake.training`, `nicolas.admin` `@brasaland.example`) y dos reportes internos
(«Medellín Centro — Friday stockout» en Operaciones y «Carnes del Valle rate change» en Compras). Contraseña de desarrollo: variable `SEED_USER_PASSWORD` (o la de desarrollo por defecto; **no usar en producción**).

## Migración de cuentas existentes

Al arrancar, los usuarios con el rol plano anterior se migran: `user → employee`, `manager → supervisor`, `admin → admin`, **sin departamento**.
Un usuario sin departamento recibe 403 explícito en datos departamentales hasta que un Admin lo asigne (vista **Roles y accesos**).
Atención con cuentas de servicio (p. ej. el usuario del agente/MCP): asignarles departamento (`restaurant_operations`) o recibirán 403.
Protección: no se puede degradar ni eliminar al último Admin activo (409).

## Interfaz (backoffice)

- `/auth/me` devuelve rol, rango, departamento y capacidades; la UI oculta o deshabilita crear/actualizar/aprobar según la capacidad (el servidor sigue siendo la autoridad).
- Vista solo Admin: `/admin/access` (listar/crear roles y departamentos, asignar rol y departamento por separado). Empleado/Supervisor ven un 403; la API también responde 403.

## Evidencia

- `docs/security/evidence/roles-permisos-403.txt`: llamadas directas a la API (Felipe → informe de Lucía = 403, etc.).
- `docs/security/evidence/roles-permisos-tests.txt`: `pytest -v` de `services/api/tests/test_roles_permissions.py` (28 pruebas).
