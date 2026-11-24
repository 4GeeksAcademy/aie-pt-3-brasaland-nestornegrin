"""Persistencia del chat: sesiones (`ChatSession`) y sus mensajes. Es lo que se rehidrata al reconectar (`session_snapshot`).

SQLite de la biblioteca estándar. Con ruta `:memory:` (pruebas) todo vive en el proceso; con un fichero sobrevive a un reinicio del
servidor. Cada token se anexa al mensaje en curso, de modo que un corte de red o de servidor deja el parcial guardado.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone

AGENT_ID = "manager_support"
SESSION_ACTIVE, SESSION_INTERRUPTED, SESSION_CLOSED = "active", "interrupted", "closed"
MESSAGE_STREAMING, MESSAGE_COMPLETED, MESSAGE_INTERRUPTED, MESSAGE_FAILED = "streaming", "completed", "interrupted", "failed"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, user_id TEXT NOT NULL, location_id TEXT,
    status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chat_messages (
    n INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL, sequence INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_chat_messages_session ON chat_messages(session_id, n);
"""


def message_id_of(n: int) -> str:
    return f"msg_{n:04d}"


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


class ChatStore:
    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA synchronous=OFF")
            self._db.executescript(_SCHEMA)

    # ---- sesiones ----
    def get_session(self, session_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM chat_sessions WHERE session_id=?", (session_id,)).fetchone()
        return dict(row) if row else None

    def ensure_session(self, session_id: str, user_id: str, location_id: str | None) -> dict:
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO chat_sessions(session_id, agent_id, user_id, location_id, status, created_at) VALUES (?,?,?,?,?,?)",
                (session_id, AGENT_ID, user_id, location_id, SESSION_ACTIVE, _now()))
            self._db.commit()
        return self.get_session(session_id)  # type: ignore[return-value]

    def set_status(self, session_id: str, status: str) -> None:
        with self._lock:
            self._db.execute("UPDATE chat_sessions SET status=? WHERE session_id=?", (status, session_id))
            self._db.commit()

    # ---- mensajes ----
    def add_message(self, session_id: str, role: str, text: str = "", status: str = MESSAGE_COMPLETED) -> str:
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO chat_messages(session_id, role, text, status, created_at) VALUES (?,?,?,?,?)",
                (session_id, role, text, status, _now()))
            self._db.commit()
            return message_id_of(cursor.lastrowid)

    def append_token(self, message_id: str, token: str) -> int:
        """Anexa el token al mensaje y devuelve su `sequence` (1, 2, 3… dentro del mensaje)."""
        n = int(message_id.split("_")[1])
        with self._lock:
            self._db.execute("UPDATE chat_messages SET text = text || ?, sequence = sequence + 1 WHERE n=?", (token, n))
            row = self._db.execute("SELECT sequence FROM chat_messages WHERE n=?", (n,)).fetchone()
            self._db.commit()
        return row["sequence"]

    def finish_message(self, message_id: str, status: str, text: str | None = None) -> None:
        n = int(message_id.split("_")[1])
        with self._lock:
            if text is None:
                self._db.execute("UPDATE chat_messages SET status=? WHERE n=?", (status, n))
            else:
                self._db.execute("UPDATE chat_messages SET status=?, text=? WHERE n=?", (status, text, n))
            self._db.commit()

    def messages(self, session_id: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM chat_messages WHERE session_id=? ORDER BY n", (session_id,)).fetchall()
        return [{"message_id": message_id_of(r["n"]), "role": r["role"], "text": r["text"], "status": r["status"],
                 "sequence": r["sequence"], "created_at": r["created_at"]} for r in rows]

    def orphaned_streaming(self, session_id: str) -> list[str]:
        """Mensajes que quedaron «streaming» sin generación viva (el proceso murió a mitad): hay que cerrarlos."""
        return [m["message_id"] for m in self.messages(session_id) if m["status"] == MESSAGE_STREAMING]
