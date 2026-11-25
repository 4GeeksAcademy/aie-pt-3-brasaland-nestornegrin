"""Almacén SQLite. Cada cifra conserva su fila de origen; cada término contractual su cláusula y página. Los importes se guardan como TEXTO
(Decimal exacto). NUNCA se guarda texto sin pasar por `sensitive.clean`: ni términos, ni eventos, ni mensajes entre agentes."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .sensitive import clean_any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS suppliers(id TEXT PRIMARY KEY, name TEXT, country TEXT, category TEXT, currency TEXT);
CREATE TABLE IF NOT EXISTS prices(id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_id TEXT, product TEXT, unit TEXT, currency TEXT,
  month TEXT, unit_price TEXT, monthly_volume INTEGER, source_file TEXT, source_row INTEGER);
CREATE TABLE IF NOT EXISTS contracts(id TEXT PRIMARY KEY, supplier_id TEXT, file TEXT, language TEXT, pages INTEGER, loaded_at TEXT);
CREATE TABLE IF NOT EXISTS terms(id INTEGER PRIMARY KEY AUTOINCREMENT, contract_id TEXT, kind TEXT, clause TEXT, page INTEGER, quote TEXT,
  language TEXT, confidence REAL, doubtful INTEGER, params TEXT);
CREATE TABLE IF NOT EXISTS notices(id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_id TEXT, kind TEXT, ref TEXT, recorded_at TEXT);
CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE, kind TEXT, supplier_id TEXT, contract_id TEXT,
  stage INTEGER, as_of TEXT, message TEXT, detail TEXT, recipients TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS communications(id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_id TEXT, contract_id TEXT, subject TEXT, body TEXT,
  status TEXT, required_roles TEXT, created_by TEXT, created_at TEXT, decided_at TEXT, sent_at TEXT);
CREATE TABLE IF NOT EXISTS approvals(id INTEGER PRIMARY KEY AUTOINCREMENT, communication_id INTEGER, role TEXT, staff_id TEXT, decision TEXT,
  comment TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor_type TEXT, actor_id TEXT, action TEXT, subject TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, request_id TEXT, sender TEXT, recipient TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS staff(id TEXT PRIMARY KEY, name TEXT, email TEXT UNIQUE, role TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or config.DEFAULT_DB)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._memory = sqlite3.connect(":memory:", check_same_thread=False) if self.path == ":memory:" else None
        with self.conn() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def conn(self):
        c = self._memory or sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            if self._memory is None:
                c.close()

    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def run(self, sql: str, args: tuple = ()) -> int:
        with self.conn() as c:
            return c.execute(sql, args).lastrowid

    # ---- meta / directorio
    def set_meta(self, key: str, value: str) -> None:
        self.run("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def meta(self, key: str) -> str | None:
        row = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return row["value"] if row else None

    def seed_staff(self) -> None:
        for sid, name, email, role in config.STAFF:
            self.run("INSERT OR IGNORE INTO staff(id,name,email,role) VALUES(?,?,?,?)", (sid, name, email, role))

    def staff_by_email(self, email: str) -> dict | None:
        return self.one("SELECT * FROM staff WHERE lower(email)=lower(?)", (email,))

    def staff(self, staff_id: str) -> dict | None:
        return self.one("SELECT * FROM staff WHERE id=?", (staff_id,))

    # ---- eventos y mensajes (SIEMPRE redactados antes de guardar)
    def event(self, actor_type: str, actor_id: str, action: str, subject: str = "", detail: dict | None = None) -> None:
        self.run("INSERT INTO events(ts,actor_type,actor_id,action,subject,detail) VALUES(?,?,?,?,?,?)",
                 (now(), actor_type, actor_id, action, subject, json.dumps(clean_any(detail or {}), ensure_ascii=False, default=str)))

    def events(self, limit: int = 200) -> list[dict]:
        rows = self.q("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["detail"] = json.loads(r["detail"])
        return rows

    def message(self, request_id: str, sender: str, recipient: str, payload: dict) -> None:
        self.run("INSERT INTO messages(ts,request_id,sender,recipient,payload) VALUES(?,?,?,?,?)",
                 (now(), request_id, sender, recipient, json.dumps(clean_any(payload), ensure_ascii=False, default=str)))

    def messages(self, request_id: str | None = None) -> list[dict]:
        rows = self.q("SELECT * FROM messages WHERE request_id=? ORDER BY id", (request_id,)) if request_id else self.q("SELECT * FROM messages ORDER BY id")
        for r in rows:
            r["payload"] = json.loads(r["payload"])
        return rows

    # ---- avisos escritos y pruebas registradas (de ellos depende que una subida esté amparada por el contrato)
    def add_notice(self, supplier_id: str, kind: str, ref: str) -> int:
        return self.run("INSERT INTO notices(supplier_id,kind,ref,recorded_at) VALUES(?,?,?,?)", (supplier_id, kind, ref, now()))

    def notices(self, supplier_id: str, kind: str) -> list[dict]:
        return self.q("SELECT * FROM notices WHERE supplier_id=? AND kind=? ORDER BY id", (supplier_id, kind))
