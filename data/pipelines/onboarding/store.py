"""Almacén de estado del onboarding (SQLite en archivo, `ONBOARDING_DB`). Guarda SOLO el estado de cada trámite, nunca su contenido:
`paperwork` son banderas ("contrato recibido": sí/no); no existe ninguna columna para documentos de identidad, datos bancarios ni salario.

Tablas: staff (directorio de aprobadores), onboardings, stage_progress, paperwork, quiz_state, events (auditoría de cada acción, con el
actor: persona o proceso automatizado), notifications (bandeja de avisos) y question_log (dudas, ya depuradas de datos sensibles)."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .sensitive import redact

SCHEMA = """
CREATE TABLE IF NOT EXISTS staff (id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, department TEXT NOT NULL,
                                   role TEXT NOT NULL, site TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS onboardings (id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, position TEXT NOT NULL,
                                         department TEXT NOT NULL, site TEXT NOT NULL, manager_id TEXT NOT NULL, variant TEXT NOT NULL,
                                         start_date TEXT NOT NULL, status TEXT NOT NULL, current_stage INTEGER NOT NULL DEFAULT 1,
                                         created_at TEXT NOT NULL, completed_at TEXT, processing_error TEXT);
CREATE TABLE IF NOT EXISTS stage_progress (onboarding_id TEXT NOT NULL, stage INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                                            entered_at TEXT, deadline_at TEXT, completed_at TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                                            reminder_sent_at TEXT, overdue_notified_at TEXT, delay_notified_at TEXT,
                                            quiz_failure_notified_at TEXT, rejections INTEGER NOT NULL DEFAULT 0, last_comment TEXT,
                                            PRIMARY KEY (onboarding_id, stage));
CREATE TABLE IF NOT EXISTS paperwork (onboarding_id TEXT PRIMARY KEY, contract_received INTEGER NOT NULL DEFAULT 0,
                                       payroll_docs_received INTEGER NOT NULL DEFAULT 0, shadow_day_confirmed INTEGER NOT NULL DEFAULT 0,
                                       accesses_confirmed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS quiz_state (onboarding_id TEXT PRIMARY KEY, stage INTEGER NOT NULL, attempt INTEGER NOT NULL,
                                        question_ids TEXT NOT NULL, failed_sources TEXT NOT NULL DEFAULT '[]', last_score REAL);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, onboarding_id TEXT, actor_type TEXT NOT NULL,
                                    actor_id TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, recipient_kind TEXT NOT NULL,
                                           recipient_id TEXT NOT NULL, onboarding_id TEXT, kind TEXT NOT NULL, stage INTEGER,
                                           message TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS question_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, onboarding_id TEXT NOT NULL,
                                          question TEXT NOT NULL, answered INTEGER NOT NULL, sources TEXT NOT NULL DEFAULT '[]');
"""


def iso(moment: datetime | None) -> str | None:
    return moment.astimezone(timezone.utc).isoformat() if moment else None


def parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def default_db_path() -> str:
    return os.environ.get("ONBOARDING_DB") or str(config.DEFAULT_DB)


class OnboardingStore:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = str(path or default_db_path())
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    @contextmanager
    def _tx(self):
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _one(self, sql: str, args=()) -> dict | None:
        with self._lock:
            row = self._conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def _all(self, sql: str, args=()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- directorio de personas autorizadas ------------------------------------------------------------------------------
    def upsert_staff(self, staff_id: str, name: str, email: str, department: str, role: str, site: str) -> None:
        with self._tx() as c:
            c.execute("INSERT INTO staff (id,name,email,department,role,site) VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                      "name=excluded.name,email=excluded.email,department=excluded.department,role=excluded.role,site=excluded.site",
                      (staff_id, name, email.lower(), department, role, site))

    def staff(self, staff_id: str) -> dict | None:
        return self._one("SELECT * FROM staff WHERE id=?", (staff_id,))

    def staff_by_email(self, email: str) -> dict | None:
        return self._one("SELECT * FROM staff WHERE email=?", (email.lower(),))

    def staff_with_role(self, role: str) -> list[dict]:
        return self._all("SELECT * FROM staff WHERE role=? ORDER BY id", (role,))

    # ---- incorporaciones --------------------------------------------------------------------------------------------------
    def create_onboarding(self, record: dict, now: datetime) -> None:
        with self._tx() as c:
            c.execute("INSERT INTO onboardings (id,name,email,position,department,site,manager_id,variant,start_date,status,current_stage,created_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (record["id"], record["name"], record["email"].lower(), record["position"], record["department"], record["site"],
                       record["manager_id"], record["variant"], record["start_date"], "creating", 1, iso(now)))
            c.execute("INSERT INTO paperwork (onboarding_id) VALUES (?)", (record["id"],))
            for stage in config.STAGES:
                c.execute("INSERT INTO stage_progress (onboarding_id,stage) VALUES (?,?)", (record["id"], stage.number))

    def onboarding(self, onboarding_id: str) -> dict | None:
        return self._one("SELECT * FROM onboardings WHERE id=?", (onboarding_id,))

    def onboarding_by_email(self, email: str) -> dict | None:
        return self._one("SELECT * FROM onboardings WHERE email=?", (email.lower(),))

    def onboardings(self, status: str | None = None) -> list[dict]:
        if status:
            return self._all("SELECT * FROM onboardings WHERE status=? ORDER BY created_at, id", (status,))
        return self._all("SELECT * FROM onboardings ORDER BY created_at, id")

    def update_onboarding(self, onboarding_id: str, **fields) -> None:
        columns = ", ".join(f"{name}=?" for name in fields)
        with self._tx() as c:
            c.execute(f"UPDATE onboardings SET {columns} WHERE id=?", (*fields.values(), onboarding_id))

    # ---- etapas -----------------------------------------------------------------------------------------------------------
    def stage(self, onboarding_id: str, number: int) -> dict:
        return self._one("SELECT * FROM stage_progress WHERE onboarding_id=? AND stage=?", (onboarding_id, number))

    def stages(self, onboarding_id: str) -> list[dict]:
        return self._all("SELECT * FROM stage_progress WHERE onboarding_id=? ORDER BY stage", (onboarding_id,))

    def update_stage(self, onboarding_id: str, number: int, **fields) -> None:
        columns = ", ".join(f"{name}=?" for name in fields)
        with self._tx() as c:
            c.execute(f"UPDATE stage_progress SET {columns} WHERE onboarding_id=? AND stage=?", (*fields.values(), onboarding_id, number))

    def activate_stage(self, onboarding_id: str, number: int, entered_at: datetime, deadline_at: datetime) -> None:
        """Entra (o vuelve a entrar tras un rechazo) en la etapa: los avisos de plazo se rearman para el nuevo intento."""
        with self._tx() as c:
            c.execute("UPDATE stage_progress SET status='active', entered_at=COALESCE(entered_at, ?), deadline_at=?, attempts=0 "
                      "WHERE onboarding_id=? AND stage=?", (iso(entered_at), iso(deadline_at), onboarding_id, number))
            c.execute("UPDATE onboardings SET current_stage=?, status='active' WHERE id=?", (number, onboarding_id))
            c.execute("DELETE FROM quiz_state WHERE onboarding_id=?", (onboarding_id,))

    def paperwork(self, onboarding_id: str) -> dict:
        return self._one("SELECT * FROM paperwork WHERE onboarding_id=?", (onboarding_id,))

    def set_paperwork(self, onboarding_id: str, **flags: bool) -> None:
        allowed = {"contract_received", "payroll_docs_received", "shadow_day_confirmed", "accesses_confirmed"}
        if set(flags) - allowed:
            raise ValueError(f"campos no permitidos: {sorted(set(flags) - allowed)}")  # no hay dónde guardar contenido sensible
        columns = ", ".join(f"{name}=?" for name in flags)
        with self._tx() as c:
            c.execute(f"UPDATE paperwork SET {columns} WHERE onboarding_id=?", (*[int(v) for v in flags.values()], onboarding_id))

    # ---- comprobación en curso --------------------------------------------------------------------------------------------
    def quiz(self, onboarding_id: str) -> dict | None:
        row = self._one("SELECT * FROM quiz_state WHERE onboarding_id=?", (onboarding_id,))
        if row:
            row["question_ids"] = json.loads(row["question_ids"])
            row["failed_sources"] = json.loads(row["failed_sources"])
        return row

    def set_quiz(self, onboarding_id: str, stage: int, attempt: int, question_ids: list[str], failed_sources: list[str], last_score: float | None) -> None:
        with self._tx() as c:
            c.execute("INSERT INTO quiz_state (onboarding_id,stage,attempt,question_ids,failed_sources,last_score) VALUES (?,?,?,?,?,?) "
                      "ON CONFLICT(onboarding_id) DO UPDATE SET stage=excluded.stage,attempt=excluded.attempt,question_ids=excluded.question_ids,"
                      "failed_sources=excluded.failed_sources,last_score=excluded.last_score",
                      (onboarding_id, stage, attempt, json.dumps(question_ids), json.dumps(failed_sources), last_score))

    # ---- auditoría y avisos -----------------------------------------------------------------------------------------------
    def log_event(self, onboarding_id: str | None, actor_type: str, actor_id: str, action: str, detail: dict, now: datetime) -> None:
        clean, _ = redact(json.dumps(detail, ensure_ascii=False, default=str))
        with self._tx() as c:
            c.execute("INSERT INTO events (ts,onboarding_id,actor_type,actor_id,action,detail) VALUES (?,?,?,?,?,?)",
                      (iso(now), onboarding_id, actor_type, actor_id, action, clean))

    def events(self, onboarding_id: str) -> list[dict]:
        rows = self._all("SELECT * FROM events WHERE onboarding_id=? ORDER BY id", (onboarding_id,))
        for row in rows:
            row["detail"] = json.loads(row["detail"])
        return rows

    def notify(self, recipient_kind: str, recipient_id: str, onboarding_id: str | None, kind: str, stage: int | None, message: str, now: datetime) -> None:
        clean, _ = redact(message)
        with self._tx() as c:
            c.execute("INSERT INTO notifications (ts,recipient_kind,recipient_id,onboarding_id,kind,stage,message) VALUES (?,?,?,?,?,?,?)",
                      (iso(now), recipient_kind, recipient_id, onboarding_id, kind, stage, clean))

    def notifications(self, recipient_kind: str, recipient_id: str) -> list[dict]:
        return self._all("SELECT * FROM notifications WHERE recipient_kind=? AND recipient_id=? ORDER BY id DESC", (recipient_kind, recipient_id))

    def all_notifications(self, onboarding_id: str) -> list[dict]:
        return self._all("SELECT * FROM notifications WHERE onboarding_id=? ORDER BY id", (onboarding_id,))

    def log_question(self, onboarding_id: str, question: str, answered: bool, sources: list[str], now: datetime) -> None:
        clean, _ = redact(question)
        with self._tx() as c:
            c.execute("INSERT INTO question_log (ts,onboarding_id,question,answered,sources) VALUES (?,?,?,?,?)",
                      (iso(now), onboarding_id, clean[:500], int(answered), json.dumps(sources)))

    def questions(self, onboarding_id: str) -> list[dict]:
        return self._all("SELECT * FROM question_log WHERE onboarding_id=? ORDER BY id", (onboarding_id,))
