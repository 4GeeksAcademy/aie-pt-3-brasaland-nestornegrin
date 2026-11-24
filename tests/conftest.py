"""Configuración común de los tests del monorepo que viven en `tests/` (hoy: `tests/pipelines/`).

- Pone la raíz del monorepo en `sys.path` para que `data.pipelines…` y `data.process…` se importen igual que
  en `python data/pipelines/pipeline.py`.
- Aísla Prefect ANTES de importarlo: su carpeta de trabajo (base de datos efímera y resultados en caché) va a un
  directorio temporal y la telemetría anónima se desactiva, así los tests no dejan nada en `~/.prefect`.
- No lee `DATABASE_URL`: estos tests no necesitan, ni deben tocar, ninguna base de datos.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("PREFECT_HOME", tempfile.mkdtemp(prefix="prefect-tests-"))
os.environ.setdefault("PREFECT_SERVER_ANALYTICS_ENABLED", "false")
os.environ.setdefault("DO_NOT_TRACK", "1")
