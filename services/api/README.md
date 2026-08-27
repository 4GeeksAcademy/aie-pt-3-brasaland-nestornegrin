# API de incidencias Brasaland

API interna FastAPI para analizar ficheros CSV de incidencias postventa. La
validación y las métricas se importan desde `scripts.analyze`, por lo que el
script de terminal y el endpoint comparten exactamente la misma lógica.

## Ejecución local

```bash
cd services/api
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --app-dir ../..
```

Endpoints:

- `POST /api/incidents/analyze` recibe `file` como `multipart/form-data`.
- `GET /api/incidents/results/export` descarga el último resultado como CSV.

Los resultados se mantienen en memoria para desarrollo local. No se guardan
datos personales ni el contenido original del fichero.