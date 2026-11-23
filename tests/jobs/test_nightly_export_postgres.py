"""Script nocturno contra Postgres REAL: export a CSV y carrera entre PROCESOS (DEV-53).

⚠️  DESTRUCTIVO: cada test hace TRUNCATE de `job_runs` y de `telemetry_events`. Es OPT-IN, igual que
`services/api/tests/test_pipeline_integration.py`: exige `PIPELINE_INTEGRATION_TESTS=1` y una `DATABASE_URL` de
Postgres de PRUEBAS (jamás la de Supabase con datos reales):

    PIPELINE_INTEGRATION_TESTS=1 DATABASE_URL=postgresql+psycopg://… python -m pytest tests/jobs/test_nightly_export_postgres.py
"""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

URL = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    os.getenv("PIPELINE_INTEGRATION_TESTS") != "1" or not URL.startswith("postgres"),
    reason="Destructivo: requiere PIPELINE_INTEGRATION_TESTS=1 y una DATABASE_URL de Postgres de PRUEBAS",
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "nightly_export.py"
DAY = date(2026, 10, 14)
UTC = timezone.utc


def _load_script():
    spec = importlib.util.spec_from_file_location("nightly_export_pg", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def engine():
    from services import job_runner

    eng = create_engine(URL)
    job_runner.ensure_job_runs_table(eng)
    with eng.begin() as conn:
        conn.execute(text("TRUNCATE public.job_runs RESTART IDENTITY"))
        conn.execute(text("TRUNCATE public.telemetry_events RESTART IDENTITY"))
    yield eng
    eng.dispose()


def _event(engine, when: datetime, event_type: str = "outbound_order_created", tags: dict | None = None) -> str:
    event_id = str(uuid4())
    with engine.begin() as conn:
        conn.execute(
            text('INSERT INTO telemetry_events (event_id, event_type, "timestamp", service, user_id, session_id, tags) VALUES (:e, :t, :w, \'backend\', \'1\', \'s\', CAST(:tags AS jsonb))'),
            {"e": event_id, "t": event_type, "w": when, "tags": json.dumps(tags or {"quantity": 2})},
        )
    return event_id


def test_el_csv_contiene_solo_el_dia_objetivo_en_utc_y_no_se_reexporta(engine, tmp_path, monkeypatch):
    nightly = _load_script()
    monkeypatch.setattr(nightly, "EXPORT_DIR", tmp_path)
    inside = [_event(engine, datetime(2026, 10, 14, 0, 0, 0, tzinfo=UTC)), _event(engine, datetime(2026, 10, 14, 23, 59, 59, tzinfo=UTC), "stock_alert")]
    _event(engine, datetime(2026, 10, 13, 23, 59, 59, tzinfo=UTC))  # día anterior
    _event(engine, datetime(2026, 10, 15, 0, 0, 0, tzinfo=UTC))  # día siguiente

    path, rows = nightly.export_telemetry_csv(engine, DAY)
    assert path.name == "telemetry_2026-10-14.csv" and rows == 2
    with path.open(newline="") as handle:
        data = list(csv.DictReader(handle))
    assert [r["event_id"] for r in data] == inside
    assert data[0]["timestamp"].endswith("+00:00")  # siempre en UTC
    assert json.loads(data[0]["tags"]) == {"quantity": 2}

    _event(engine, datetime(2026, 10, 14, 12, 0, tzinfo=UTC))  # llega un evento nuevo DESPUÉS de exportar
    again, none_rows = nightly.export_telemetry_csv(engine, DAY)
    assert again == path and none_rows is None  # «solo si el archivo no existe»
    assert len(list(csv.DictReader(path.open(newline="")))) == 2
    assert not list(tmp_path.glob("*.tmp"))


def test_un_dia_sin_eventos_deja_un_csv_solo_con_cabecera(engine, tmp_path, monkeypatch):
    nightly = _load_script()
    monkeypatch.setattr(nightly, "EXPORT_DIR", tmp_path)
    path, rows = nightly.export_telemetry_csv(engine, DAY)
    assert rows == 0 and path.read_text().strip() == ",".join(nightly.CSV_COLUMNS)


def _spawn(day: str, env_extra: dict[str, str]) -> subprocess.Popen:
    env = {**os.environ, "TARGET_DATE": day, **env_extra}
    return subprocess.Popen([sys.executable, str(SCRIPT)], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def test_dos_procesos_a_la_vez_solo_uno_trabaja_y_el_otro_aborta_en_silencio(engine, tmp_path):
    _event(engine, datetime(2026, 10, 14, 10, 0, tzinfo=UTC))
    marker = tmp_path / "pipeline_runs.txt"
    slow = f"{sys.executable} -c \"import time; open(r'{marker}', 'a').write('x'); time.sleep(4)\""
    extra = {"NIGHTLY_PIPELINE_CMD": slow, "NIGHTLY_EXPORT_DIR": str(tmp_path / "raw")}
    procs = [_spawn("2026-10-14", extra) for _ in range(3)]  # tres instancias arrancando juntas
    outputs = [p.communicate(timeout=60)[0] for p in procs]

    assert [p.returncode for p in procs] == [0, 0, 0]  # ninguna falla: la perdedora aborta en silencio
    assert marker.read_text() == "x"  # el pipeline se lanzó UNA sola vez
    with engine.connect() as conn:
        statuses = [r[0] for r in conn.execute(text("SELECT status FROM job_runs ORDER BY id"))]
    assert statuses == ["completed"]  # ni filas zombi ni filas de las perdedoras
    assert sum("Fin run_id" in out for out in outputs) == 1
    assert sum("Cancelado" in out for out in outputs) == 2


def test_un_proceso_matado_con_sigterm_no_deja_processing(engine, tmp_path):
    extra = {"NIGHTLY_PIPELINE_CMD": f"{sys.executable} -c \"import time; time.sleep(30)\"", "NIGHTLY_EXPORT_DIR": str(tmp_path / "raw")}
    proc = _spawn("2026-10-14", extra)
    deadline = time.time() + 20
    while time.time() < deadline:
        with engine.connect() as conn:
            if conn.execute(text("SELECT 1 FROM job_runs WHERE status = 'processing'")).first():
                break
        time.sleep(0.2)
    proc.terminate()
    proc.communicate(timeout=30)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT status, error_message FROM job_runs")).all()
    assert [r[0] for r in rows] == ["failed"] and "SIGTERM" in rows[0][1]
