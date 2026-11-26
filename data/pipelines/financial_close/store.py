"""Dos almacenes SEPARADOS. `DataStore`: datos financieros normalizados (los escribe SOLO la ingesta; el agente los abre en SOLO LECTURA).
`CloseStore`: informes, revisiones, eventos del agente, mensajes salientes y directorio. Nada se guarda sin pasar por `sensitive.clean`."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .sensitive import clean_any


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _Base:
    SCHEMA = ""

    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(self.SCHEMA)

    @contextmanager
    def conn(self, readonly: bool = False):
        c = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=30) if readonly else sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            yield c
            if not readonly:
                c.commit()
        finally:
            c.close()

    def q(self, sql: str, args: tuple = (), readonly: bool = False) -> list[dict]:
        with self.conn(readonly) as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def run(self, sql: str, args: tuple = ()) -> int:
        with self.conn() as c:
            return c.execute(sql, args).lastrowid


class DataStore(_Base):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY AUTOINCREMENT, period TEXT, kind TEXT, file TEXT, row INTEGER, entry_id TEXT,
      date TEXT, country TEXT, category TEXT, currency TEXT, amount TEXT, description TEXT, source_ref TEXT, metric TEXT,
      status TEXT, reasons TEXT);
    CREATE INDEX IF NOT EXISTS ix_records ON records(period, kind, country, category);
    CREATE TABLE IF NOT EXISTS loads(period TEXT PRIMARY KEY, loaded_at TEXT, summary TEXT);
    """

    def readonly_query(self, sql: str, args: tuple = ()) -> list[dict]:
        """Lo que usa el agente: conexión abierta con `mode=ro`; cualquier escritura falla en SQLite."""
        return self.q(sql, args, readonly=True)


class CloseStore(_Base):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY AUTOINCREMENT, period TEXT, version INTEGER, status TEXT, content TEXT,
      content_hash TEXT, markdown TEXT, created_at TEXT, decided_at TEXT, distributed_at TEXT, based_on_review INTEGER, UNIQUE(period, version));
    CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY AUTOINCREMENT, report_id INTEGER, staff_id TEXT, decision TEXT, comment TEXT, ts TEXT);
    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor_type TEXT, actor_id TEXT, action TEXT, subject TEXT, detail TEXT);
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, recipient_id TEXT, report_id INTEGER, subject TEXT, body TEXT);
    CREATE TABLE IF NOT EXISTS staff(id TEXT PRIMARY KEY, name TEXT, email TEXT UNIQUE, role TEXT);
    CREATE TABLE IF NOT EXISTS schedule_runs(period TEXT PRIMARY KEY, started_at TEXT, report_id INTEGER);
    """

    def __init__(self, path):
        super().__init__(path)
        for sid, name, email, role in config.STAFF:
            self.run("INSERT OR IGNORE INTO staff(id,name,email,role) VALUES(?,?,?,?)", (sid, name, email, role))

    def staff_by_email(self, email: str) -> dict | None:
        return self.one("SELECT * FROM staff WHERE lower(email)=lower(?)", (email,))

    def staff(self, staff_id: str) -> dict | None:
        return self.one("SELECT * FROM staff WHERE id=?", (staff_id,))

    def event(self, actor_type: str, actor_id: str, action: str, subject: str = "", detail: dict | None = None) -> None:
        self.run("INSERT INTO events(ts,actor_type,actor_id,action,subject,detail) VALUES(?,?,?,?,?,?)",
                 (now(), actor_type, actor_id, action, subject, json.dumps(clean_any(detail or {}), ensure_ascii=False, default=str)))

    def events(self, limit: int = 300) -> list[dict]:
        rows = self.q("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["detail"] = json.loads(r["detail"])
        return rows

    def message(self, kind: str, recipient_id: str, report_id: int, subject: str, body: str) -> None:
        from .sensitive import clean
        self.run("INSERT INTO messages(ts,kind,recipient_id,report_id,subject,body) VALUES(?,?,?,?,?,?)",
                 (now(), kind, recipient_id, report_id, clean(subject), clean(body)))

    def messages(self, report_id: int | None = None) -> list[dict]:
        return self.q("SELECT * FROM messages WHERE report_id=? ORDER BY id", (report_id,)) if report_id else self.q("SELECT * FROM messages ORDER BY id")
