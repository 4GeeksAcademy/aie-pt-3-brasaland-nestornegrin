"""`scripts/nightly_export.py`: orquestación, idempotencia, lock y «nada se queda en processing» (DEV-53).

El pipeline real se sustituye por un comando trivial (`NIGHTLY_PIPELINE_CMD`) y el export a CSV se prueba aparte
sobre SQLite; el export contra Postgres real y la carrera entre procesos están en `test_nightly_export_postgres.py`.
"""
from __future__ import annotations

import importlib.util
import logging
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("nightly_export", ROOT / "scripts" / "nightly_export.py")
nightly = importlib.util.module_from_spec(spec)
sys.modules["nightly_export"] = nightly
spec.loader.exec_module(nightly)

DAY = date(2026, 10, 14)


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    """CSV a una carpeta temporal y un pipeline simulado que cuenta cuántas veces se lanzó."""
    monkeypatch.setattr(nightly, "EXPORT_DIR", tmp_path / "raw")
    counter = tmp_path / "pipeline_calls.txt"
    monkeypatch.setenv("NIGHTLY_PIPELINE_CMD", f"{sys.executable} -c \"open(r'{counter}', 'a').write('x')\"")
    monkeypatch.setattr(nightly, "export_telemetry_csv", _fake_export)
    return counter


def _fake_export(engine, target_date):
    path = nightly.csv_path_for(target_date)
    if path.exists():
        return path, None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("id,event_id\n1,a\n")
    return path, 1


def calls(counter: Path) -> int:
    return len(counter.read_text()) if counter.exists() else 0


# ------------------------------------------------------------------ fecha objetivo
def test_target_date_por_defecto_es_ayer_en_utc():
    assert nightly.resolve_target_date({}, today=date(2026, 1, 1)) == date(2025, 12, 31)
    assert nightly.resolve_target_date({}) == datetime.now(timezone.utc).date() - (datetime.now(timezone.utc).date() - nightly.resolve_target_date({}))
    assert (datetime.now(timezone.utc).date() - nightly.resolve_target_date({})).days == 1


def test_target_date_de_entorno_sobrescribe_el_defecto():
    assert nightly.resolve_target_date({"TARGET_DATE": "2025-01-15"}) == date(2025, 1, 15)


def test_target_date_invalida_da_un_error_claro():
    with pytest.raises(ValueError, match="TARGET_DATE='ayer'"):
        nightly.resolve_target_date({"TARGET_DATE": "ayer"})


# ------------------------------------------------------------------ máquina de estados
def test_ejecucion_correcta_deja_completed_con_target_date_y_exporta_csv(engine, rows, _sandbox):
    assert nightly.run(engine, DAY) == 0
    assert rows() == [("nightly_export", "2026-10-14", "completed", None)]
    assert nightly.csv_path_for(DAY).exists() and calls(_sandbox) == 1


def test_idempotente_dos_ejecuciones_el_mismo_dia_equivalen_a_una(engine, rows, _sandbox, caplog):
    assert nightly.run(engine, DAY) == 0
    first_csv = nightly.csv_path_for(DAY).read_text()
    assert nightly.run(engine, DAY) == 0
    assert rows() == [("nightly_export", "2026-10-14", "completed", None)]  # ni una fila nueva
    assert calls(_sandbox) == 1  # el pipeline no se relanzó
    assert nightly.csv_path_for(DAY).read_text() == first_csv


def test_dias_distintos_son_ejecuciones_independientes(engine, rows, _sandbox):
    nightly.run(engine, DAY)
    nightly.run(engine, date(2026, 10, 15))
    assert [r[1] for r in rows()] == ["2026-10-14", "2026-10-15"] and calls(_sandbox) == 2


def test_si_otra_instancia_esta_processing_aborta_en_silencio(engine, rows, _sandbox):
    from services import job_runner as jr

    other = jr.create_job_run(engine, "nightly_export", date(2026, 10, 13))
    jr.mark_processing(engine, other)
    assert nightly.run(engine, DAY) == 0  # sale bien, sin error
    assert rows() == [("nightly_export", "2026-10-13", "processing", None)]  # no creó nada
    assert calls(_sandbox) == 0 and not nightly.csv_path_for(DAY).exists()


def test_fallo_del_pipeline_deja_failed_con_el_mensaje_y_nada_en_processing(engine, rows, monkeypatch):
    monkeypatch.setenv("NIGHTLY_PIPELINE_CMD", f"{sys.executable} -c \"import sys; sys.stderr.write('Connection refused\\n'); sys.exit(3)\"")
    assert nightly.run(engine, DAY) == 1
    [(job, day, status, error)] = rows()
    assert (job, day, status) == ("nightly_export", "2026-10-14", "failed") and "código 3" in error and "Connection refused" in error
    assert not any(r[2] in ("pending", "processing") for r in rows())


def test_fallo_en_el_export_tambien_cierra_el_registro(engine, rows, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("la BD se cayó")

    monkeypatch.setattr(nightly, "export_telemetry_csv", broken)
    assert nightly.run(engine, DAY) == 1
    assert rows() == [("nightly_export", "2026-10-14", "failed", "RuntimeError: la BD se cayó")]


def test_sigint_o_sigterm_no_dejan_processing(engine, rows, monkeypatch):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(nightly, "export_telemetry_csv", interrupted)
    with pytest.raises(KeyboardInterrupt):
        nightly.run(engine, DAY)
    assert [r[2] for r in rows()] == ["failed"]


def test_tras_un_failed_la_siguiente_ejecucion_del_mismo_dia_reintenta(engine, rows, _sandbox, monkeypatch):
    good_cmd = _sandbox  # el fixture dejó el comando bueno en el entorno; guardamos y rompemos solo la primera vez
    monkeypatch.setenv("NIGHTLY_PIPELINE_CMD", f"{sys.executable} -c \"import sys; sys.exit(1)\"")
    assert nightly.run(engine, DAY) == 1
    monkeypatch.setenv("NIGHTLY_PIPELINE_CMD", f"{sys.executable} -c \"open(r'{good_cmd}', 'a').write('x')\"")
    assert nightly.run(engine, DAY) == 0
    assert [r[2] for r in rows()] == ["failed", "completed"]
    assert calls(_sandbox) == 1


def test_proceso_muerto_deja_un_processing_zombi_que_se_recupera_a_la_noche_siguiente(engine, rows, _sandbox, monkeypatch):
    from services import job_runner as jr

    zombie = jr.create_job_run(engine, "nightly_export", date(2026, 10, 13))
    jr.mark_processing(engine, zombie)
    with engine.begin() as conn:
        conn.execute(text("UPDATE job_runs SET started_at = :t WHERE id = :id"), {"t": datetime(2026, 10, 13, 2, 0, tzinfo=timezone.utc), "id": zombie})
    assert nightly.run(engine, DAY) == 0
    assert [r[2] for r in rows()] == ["failed", "completed"]
    assert "obsoleto" in rows()[0][3]


# ------------------------------------------------------------------ logs
def test_cada_linea_de_log_lleva_timestamp_job_y_estado(engine, capsys, monkeypatch):
    monkeypatch.setenv("NIGHTLY_PIPELINE_CMD", f"{sys.executable} -c \"import sys; sys.exit(1)\"")
    nightly.run(engine, DAY)
    nightly.run(engine, DAY)  # segunda: reintenta y vuelve a fallar
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert lines
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z \| (INFO|ERROR) \| job=nightly_export \| status=(pending|processing|completed|failed) \| .+")
    assert all(pattern.match(l) for l in lines), lines
    assert any("| ERROR |" in l and "status=failed" in l for l in lines)


def test_omision_por_duplicado_se_registra_como_info(engine, capsys):
    nightly.run(engine, DAY)
    capsys.readouterr()
    nightly.run(engine, DAY)
    out = capsys.readouterr().out
    assert "INFO" in out and "Omitido por duplicado" in out and "ERROR" not in out


# ------------------------------------------------------------------ independencia de FastAPI
def test_el_script_no_importa_fastapi_ni_la_app():
    source = (ROOT / "scripts" / "nightly_export.py").read_text()
    assert not re.search(r"^\s*(from|import)\s+(fastapi|app\b|uvicorn|apscheduler)", source, re.MULTILINE)
    result = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, '.'); import importlib.util as u; s=u.spec_from_file_location('n','scripts/nightly_export.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print('fastapi' in sys.modules)"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.stdout.strip() == "False", result.stderr
