# API operativa de Brasaland

API interna FastAPI para analizar incidencias postventa y gestionar el
directorio de proveedores. El directorio usa TinyDB como fuente persistente
local y se inicializa con 10 proveedores al arrancar por primera vez.

## Ejecución local

```bash
cd services/api
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --app-dir ../..
```

Para cargar el directorio inicial sin duplicados: `uv run seed`.

Endpoints:

- `POST /api/incidents/analyze` recibe `file` como `multipart/form-data`.
- `GET /api/incidents/results/export` descarga el último resultado como CSV.
- `GET /api/suppliers` lista proveedores y acepta `country` y `category` como filtros.
- `GET /api/suppliers/country/{country}` y `GET /api/suppliers/category/{category}` son búsquedas directas.
- `POST /api/suppliers` crea un proveedor validado por Pydantic.
- `GET /api/suppliers/{id}` devuelve el detalle; `PATCH /api/suppliers/{id}/rate` actualiza la tarifa y registra `updated_at`.
- `PATCH /api/suppliers/{id}/status` activa o suspende; `DELETE /api/suppliers/{id}` elimina un proveedor.

Los resultados se mantienen en memoria para desarrollo local. No se guardan
datos personales ni el contenido original del fichero. Los proveedores se
guardan en `services/api/suppliers.json` (ignorado por Git).

Categorías válidas: `Carnes`, `Vegetales`, `Lácteos`, `Bebidas`, `Empaques`.
Estados válidos: `Activo`, `Suspendido`.