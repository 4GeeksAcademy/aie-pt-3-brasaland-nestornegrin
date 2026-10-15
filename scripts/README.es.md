# Carpeta `scripts`

Esta carpeta contiene **scripts auxiliares** del monorepo: automatizaciones de desarrollo, utilidades de mantenimiento, tareas repetitivas (setup, lint, migraciones, generación de datos, etc.) y tooling interno.

- **Propósito principal**: agrupar herramientas de soporte que no pertenecen a una app/agente/pipeline específico, pero facilitan el trabajo del equipo.
- **Recomendación**: documenta cada script (qué hace, parámetros, requisitos, ejemplos de uso) y procura que sean reproducibles (y seguros) en distintos entornos.

## Análisis de incidencias

`analyze.py` valida y resume CSV de incidencias sin enviar el contenido a
servicios externos. Usa la misma lógica que la API y excluye de las métricas
los registros inválidos, pero muestra todos sus motivos.

```bash
python3 scripts/analyze.py data/raw/incidents-COMPANY.csv
```

Responde `s` al final para escribir `results.csv`. Para cambiar la ruta de
salida usa `--output ruta/resultados.csv`.

## Script nocturno de telemetría (`nightly_export.py`)

Exporta a CSV los eventos de `telemetry_events` del día anterior (UTC), lanza el pipeline de datos como subproceso y deja
constancia en la tabla `job_runs`. Es un **proceso independiente de la API** (no importa FastAPI).

```bash
python scripts/nightly_export.py                         # ayer (UTC)
TARGET_DATE=2026-10-14 python scripts/nightly_export.py  # un día concreto, sin tocar el código
```

- **Estados** (`services/job_runner/`): `pending → processing → completed | failed`. `processing` ES el lock: si otra
  instancia está `processing`, esta aborta en silencio. Si ya hay un `completed` para ese `target_date`, no repite nada.
- **Salida:** `data/raw/telemetry_YYYY-MM-DD.csv` (solo si no existe; es respaldo/auditoría, el pipeline lee de la BD).
- **Códigos de salida:** 0 completado u omitido · 1 falló · 2 configuración inválida (`TARGET_DATE`, sin BD).
- **Disparador:** crontab, ver [`infra/cron/`](../infra/cron/README.md).
- **Tests:** `python -m pytest tests/jobs`.
