"""`services/job_runner`: la máquina de estados pending → processing → completed | failed y el lock (DEV-53)."""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from services import job_runner as jr

DAY = date(2026, 10, 14)
JOB = "nightly_export"


def test_create_deja_el_registro_en_pending_con_su_target_date(engine):
    run_id = jr.create_job_run(engine, JOB, DAY)
    run = jr.get_job_run(engine, run_id)
    assert (run.job_name, run.target_date, run.status) == (JOB, DAY, "pending")
    assert run.started_at is None and run.finished_at is None and run.error_message is None and run.created_at is not None


def test_camino_feliz_pending_processing_completed(engine):
    run_id = jr.create_job_run(engine, JOB, DAY)
    assert jr.mark_processing(engine, run_id) is True
    assert jr.get_job_run(engine, run_id).status == "processing"
    assert jr.get_job_run(engine, run_id).started_at is not None
    assert jr.mark_completed(engine, run_id) is True
    run = jr.get_job_run(engine, run_id)
    assert run.status == "completed" and run.finished_at is not None and run.error_message is None


def test_failed_guarda_el_mensaje_y_libera_el_lock(engine):
    run_id = jr.create_job_run(engine, JOB, DAY)
    jr.mark_processing(engine, run_id)
    assert jr.has_processing_lock(engine, JOB) is True
    jr.mark_failed(engine, run_id, "ValueError: boom")
    run = jr.get_job_run(engine, run_id)
    assert (run.status, run.error_message) == ("failed", "ValueError: boom") and run.finished_at is not None
    assert jr.has_processing_lock(engine, JOB) is False


def test_un_mensaje_enorme_no_rompe_la_transicion_a_failed(engine):
    run_id = jr.create_job_run(engine, JOB, DAY)
    jr.mark_processing(engine, run_id)
    jr.mark_failed(engine, run_id, "x" * 50_000)
    assert len(jr.get_job_run(engine, run_id).error_message) == jr.MAX_ERROR_LENGTH


def test_processing_es_el_lock_la_segunda_fila_no_puede_tomarlo(engine):
    first = jr.create_job_run(engine, JOB, DAY)
    second = jr.create_job_run(engine, JOB, DAY)
    assert jr.mark_processing(engine, first) is True
    assert jr.mark_processing(engine, second) is False  # lo rechaza el índice único parcial, sin excepción
    assert jr.get_job_run(engine, second).status == "pending"


def test_el_lock_es_por_job_name(engine):
    a = jr.create_job_run(engine, "nightly_export", DAY)
    b = jr.create_job_run(engine, "otro_job", DAY)
    assert jr.mark_processing(engine, a) and jr.mark_processing(engine, b)


def test_carrera_real_de_hilos_solo_uno_obtiene_el_lock(engine):
    ids = [jr.create_job_run(engine, JOB, DAY) for _ in range(8)]
    barrier = threading.Barrier(len(ids))
    results: list[bool] = []

    def attempt(run_id: int) -> None:
        barrier.wait()
        results.append(jr.mark_processing(engine, run_id))

    threads = [threading.Thread(target=attempt, args=(i,)) for i in ids]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count(True) == 1 and results.count(False) == len(ids) - 1


def test_has_completed_for_date_exige_job_Y_fecha(engine):
    run_id = jr.create_job_run(engine, JOB, DAY)
    jr.mark_processing(engine, run_id)
    assert jr.has_completed_for_date(engine, JOB, DAY) is False  # processing todavía no es completed
    jr.mark_completed(engine, run_id)
    assert jr.has_completed_for_date(engine, JOB, DAY) is True
    assert jr.has_completed_for_date(engine, JOB, DAY + timedelta(days=1)) is False  # solo job_name no basta
    assert jr.has_completed_for_date(engine, "otro_job", DAY) is False


def test_un_failed_no_cuenta_como_completed_asi_que_se_puede_reintentar(engine):
    run_id = jr.create_job_run(engine, JOB, DAY)
    jr.mark_processing(engine, run_id)
    jr.mark_failed(engine, run_id, "boom")
    assert jr.has_completed_for_date(engine, JOB, DAY) is False


def test_las_transiciones_no_reescriben_registros_ya_terminados(engine):
    run_id = jr.create_job_run(engine, JOB, DAY)
    jr.mark_processing(engine, run_id)
    jr.mark_completed(engine, run_id)
    assert jr.mark_failed(engine, run_id, "tarde") is False
    assert jr.get_job_run(engine, run_id).status == "completed"


def test_delete_pending_solo_borra_pendientes(engine):
    pending = jr.create_job_run(engine, JOB, DAY)
    running = jr.create_job_run(engine, JOB, DAY)
    jr.mark_processing(engine, running)
    jr.delete_pending_run(engine, pending)
    jr.delete_pending_run(engine, running)
    assert jr.get_job_run(engine, pending) is None and jr.get_job_run(engine, running).status == "processing"


def test_fail_stale_recupera_zombis_pero_respeta_las_ejecuciones_vivas(engine):
    zombie = jr.create_job_run(engine, JOB, DAY)
    jr.mark_processing(engine, zombie)
    old = datetime.now(timezone.utc) - timedelta(hours=5)
    with engine.begin() as conn:
        conn.execute(text("UPDATE job_runs SET started_at = :t WHERE id = :id"), {"t": old, "id": zombie})
    assert jr.fail_stale_runs(engine, JOB, timedelta(hours=2)) == [zombie]
    run = jr.get_job_run(engine, zombie)
    assert run.status == "failed" and "obsoleto" in run.error_message
    assert jr.has_processing_lock(engine, JOB) is False

    alive = jr.create_job_run(engine, JOB, DAY)
    jr.mark_processing(engine, alive)
    assert jr.fail_stale_runs(engine, JOB, timedelta(hours=2)) == []
    assert jr.get_job_run(engine, alive).status == "processing"
