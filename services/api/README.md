# API operativa de Brasaland

API interna FastAPI para analizar incidencias postventa y gestionar el
directorio de proveedores. El directorio usa TinyDB como fuente persistente
local y se inicializa con 10 proveedores al arrancar por primera vez.

## Ejecución local

```bash
uv sync --project services/api
JWT_SECRET_KEY='cambia-esta-clave' ACCESS_TOKEN_EXPIRE_MINUTES=30 \
	PYTHONPATH=services/api uv run --project services/api \
	uvicorn app.main:app --reload --app-dir services/api
```

Para cargar el directorio inicial sin duplicados: `uv run seed`.

Para cargar el histórico de incidencias postventa (Hito 5) en el gestor de
incidencias, sin duplicar en reintentos:

```bash
uv run --project services/api python scripts/seed_incidents.py
```

Endpoints:

- `POST /api/incidents/analyze` recibe `file` como `multipart/form-data`.
- `GET /api/incidents/results/export` descarga el último resultado como CSV.
- `POST /api/incidents` crea una incidencia (`title`, `description`, `category`,
  `origin`, `branch`); nace siempre en estado `open`.
- `GET /api/incidents` lista incidencias; acepta `status`, `origin`, `branch`
  y `category` como filtros opcionales. Devuelve `[]` si no hay datos o no hay
  coincidencias, nunca un error.
- `GET /api/incidents/summary` devuelve totales por estado, categoría, origen
  y sede.
- `GET /api/incidents/{id}` devuelve el detalle; `404` si no existe.
- `PATCH /api/incidents/{id}/status` cambia el estado siguiendo el ciclo de
  vida `open → in_progress → resolved` (o `discarded` desde `open`/
  `in_progress`); `resolved` y `discarded` son finales. Una transición no
  permitida devuelve `400` con el mensaje de qué transiciones sí son válidas
  desde el estado actual; el mismo estado se trata como no-op (`200`).
- `GET /api/suppliers` lista proveedores y acepta `country` y `category` como filtros.
- `GET /api/suppliers/country/{country}` y `GET /api/suppliers/category/{category}` son búsquedas directas.
- `POST /api/suppliers` crea un proveedor validado por Pydantic.
- `GET /api/suppliers/{id}` devuelve el detalle; `PATCH /api/suppliers/{id}/rate` actualiza la tarifa y registra `updated_at`.
- `PATCH /api/suppliers/{id}/status` activa o suspende; `DELETE /api/suppliers/{id}` elimina un proveedor.

Los resultados se mantienen en memoria para desarrollo local. No se guardan
datos personales ni el contenido original del fichero. Los proveedores se
guardan en `services/api/suppliers.json` (ignorado por Git). Los usuarios y
perfiles se guardan exclusivamente en `users.json` y `profiles.json` de TinyDB.

Autenticación:

- `POST /auth/login` acepta `email` y `password` y devuelve un JWT.
- `GET /auth/me` y `GET/PUT /profiles/me` requieren `Authorization: Bearer <token>`.
- `POST /users` es público para registrar credenciales; el resto de `/users` requiere JWT.
- Las rutas de incidencias y proveedores también requieren JWT.

Configura siempre `JWT_SECRET_KEY` y, opcionalmente, `ACCESS_TOKEN_EXPIRE_MINUTES`.

Categorías válidas: `Carnes`, `Vegetales`, `Lácteos`, `Bebidas`, `Empaques`.
Estados válidos: `Activo`, `Suspendido`.