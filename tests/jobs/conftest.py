"""Fixtures de los tests del job nocturno (DEV-53): una base SQLite en archivo temporal con el MISMO esquema lógico
de `003_create_job_runs.sql` (incluido el índice único parcial que hace de lock). No toca ninguna base real."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

DDL = [
    """CREATE TABLE job_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_name TEXT NOT NULL,
        target_date DATE NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
        started_at TIMESTAMP, finished_at TIMESTAMP, error_message TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    "CREATE INDEX ix_job_runs_job_name_target_date ON job_runs (job_name, target_date)",
    "CREATE UNIQUE INDEX ux_job_runs_one_processing ON job_runs (job_name) WHERE status = 'processing'",
]


@pytest.fixture()
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}", connect_args={"timeout": 15})
    with eng.begin() as conn:
        for statement in DDL:
            conn.execute(text(statement))
    yield eng
    eng.dispose()


@pytest.fixture()
def rows(engine):
    """Todas las filas de job_runs como tuplas (job_name, target_date, status, error_message), en orden de id."""

    def _rows():
        with engine.connect() as conn:
            return [tuple(r) for r in conn.execute(text("SELECT job_name, target_date, status, error_message FROM job_runs ORDER BY id"))]

    return _rows
