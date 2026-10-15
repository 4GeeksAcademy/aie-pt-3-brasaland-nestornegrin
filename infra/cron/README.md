# `infra/cron` — disparador del script nocturno (DEV-53)

`nightly_export.crontab` programa `scripts/nightly_export.py` con **crontab del sistema operativo**, fuera del proceso
de FastAPI (sin APScheduler, sin `@repeat_every`, sin hooks `lifespan`).

## Instalar

```bash
mkdir -p /var/log/brasaland                       # carpeta del log (ajusta permisos al usuario que corre cron)
sed -i "s#/ruta/al/repo#$(pwd)#g" infra/cron/nightly_export.crontab   # desde la raíz del monorepo
# (y cambia /ruta/al/repo/.venv/bin/python si tu intérprete está en otro sitio)
crontab -l 2>/dev/null | cat - infra/cron/nightly_export.crontab | crontab -   # añade sin borrar tus entradas
crontab -l                                         # verificar
```

Prueba manual (sin esperar a las 02:00) sobre un día concreto: `TARGET_DATE=2026-10-14 python scripts/nightly_export.py`.

## Por qué crontab y no el scheduler del framework

- **Aislamiento:** un bloqueo, fuga de memoria o reinicio de uvicorn no afecta al job, y el job no puede bloquear ningún
  endpoint (son procesos distintos). Un scheduler dentro de FastAPI correría con 2+ workers y dispararía el job varias veces.
- **Sencillez operativa:** una línea, estándar, sin dependencias nuevas, visible con `crontab -l`.
- **Seguridad frente a solapes:** da igual cómo dispare cron; el estado `processing` en `job_runs` (con índice único
  parcial) garantiza que nunca haya dos ejecuciones en paralelo.
- **Camino a producción:** el mismo comando funciona en un contenedor scheduler dedicado (p. ej. una imagen con `cron` o un
  `CronJob` de Kubernetes con `schedule: "0 2 * * *"`); no hay que tocar el script.
