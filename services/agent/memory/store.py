"""Almacén persistente de la memoria del agente (SQLite, archivo propio).

NO es la base de conocimiento: es un archivo aparte (`AGENT_MEMORY_DB`, por defecto `data/memory/agent_memory.sqlite`)
y nunca toca las colecciones `*_knowledge` de Qdrant, que siguen siendo de solo lectura para el agente.

Tres tablas:
  proposals       una fila por propuesta: qué se propuso, quién/qué mensaje la originó, qué decidió el usuario y cuándo.
                  Un índice único parcial garantiza A LO SUMO UNA propuesta `pending` por conversación.
  memories        lo aprobado, ya consolidado (una fila activa por location + categoría + tema).
  memory_events   registro de auditoría SOLO-AÑADIR (triggers que abortan UPDATE y DELETE): propuesta, decisión,
                  escritura, sustitución, caducidad y descarte, cada uno con su actor y marca de tiempo.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .models import (
    CATEGORIES,
    MEMORY_ACTIVE,
    MEMORY_EVICTED,
    MEMORY_EXPIRED,
    MEMORY_SUPERSEDED,
    PROPOSAL_DISCARDED,
    PROPOSAL_PENDING,
    ConsolidationReport,
    MemoryProposal,
)
from .policy import normalize, slug

DEFAULT_DB_PATH = "data/memory/agent_memory.sqlite"

# Política de caducidad (por qué: ver docs/agent/memory.md). Se cuenta desde la APROBACIÓN, no desde el último uso:
# un dato falso que se consulta mucho no debe volverse inmortal.
TTL_DAYS = {"horarios": 180, "proveedores": 180, "incidentes_conocidos": 60, "preferencias_comunicacion": 365,
            "excepciones_procedimiento": 180}
MAX_PER_BUCKET = 10  # recuerdos activos por location + categoría
MAX_ACTIVE_TOTAL = 500
PENDING_TTL_HOURS = 24  # una propuesta sin respuesta se descarta: nunca queda abierta para siempre

_SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, status TEXT NOT NULL,
    location TEXT NOT NULL, category TEXT NOT NULL, topic TEXT NOT NULL, fact TEXT NOT NULL,
    rationale TEXT, language TEXT NOT NULL, replaces_id TEXT,
    origin_message TEXT, origin_run_id TEXT, proposed_by TEXT, proposed_at TEXT NOT NULL,
    decision TEXT, decision_message TEXT, decided_by TEXT, decided_at TEXT, decision_reason TEXT,
    final_fact TEXT, memory_id TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_per_conversation ON proposals(conversation_id) WHERE status = 'pending';
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY, location TEXT NOT NULL, location_key TEXT NOT NULL, category TEXT NOT NULL,
    topic TEXT NOT NULL, fact TEXT NOT NULL, language TEXT NOT NULL, status TEXT NOT NULL, proposal_id TEXT NOT NULL,
    approved_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT NOT NULL,
    last_used_at TEXT, uses INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS memories_bucket ON memories(location_key, category, status);
CREATE TABLE IF NOT EXISTS memory_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, event TEXT NOT NULL, actor TEXT NOT NULL,
    conversation_id TEXT, proposal_id TEXT, memory_id TEXT, run_id TEXT, detail TEXT);
CREATE TRIGGER IF NOT EXISTS memory_events_no_update BEFORE UPDATE ON memory_events
    BEGIN SELECT RAISE(ABORT, 'memory_events es de solo añadir'); END;
CREATE TRIGGER IF NOT EXISTS memory_events_no_delete BEFORE DELETE ON memory_events
    BEGIN SELECT RAISE(ABORT, 'memory_events es de solo añadir'); END;
"""


class PendingProposalExists(RuntimeError):
    """Ya hay una propuesta pendiente en esa conversación: no se puede abrir una segunda."""


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{os.urandom(6).hex()}"


class SqliteMemoryStore:
    def __init__(self, path: str | Path | None = None, *, now_fn: Callable[[], datetime] | None = None):
        self.path = str(path or os.environ.get("AGENT_MEMORY_DB") or DEFAULT_DB_PATH)
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()  # la API atiende peticiones en varios hilos
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(_SCHEMA)

    # ----------------------------------------------------------------------------------------------------------
    def now(self) -> datetime:
        return self.now_fn()

    def add_event(self, event: str, *, actor: str, conversation_id: str | None = None, proposal_id: str | None = None,
                  memory_id: str | None = None, run_id: str | None = None, detail: dict | None = None) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO memory_events(ts, event, actor, conversation_id, proposal_id, memory_id, run_id, detail) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (_iso(self.now()), event, actor, conversation_id, proposal_id, memory_id, run_id,
                 json.dumps(detail, ensure_ascii=False) if detail else None))
            self._db.commit()

    def events(self, *, proposal_id: str | None = None, conversation_id: str | None = None) -> list[dict]:
        clauses, params = [], []
        if proposal_id:
            clauses.append("proposal_id = ?")
            params.append(proposal_id)
        if conversation_id:
            clauses.append("conversation_id = ?")
            params.append(conversation_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._db.execute(f"SELECT * FROM memory_events {where} ORDER BY seq", params).fetchall()
        return [{**dict(row), "detail": json.loads(row["detail"]) if row["detail"] else None} for row in rows]

    # --- propuestas -----------------------------------------------------------------------------------------
    def create_proposal(self, conversation_id: str, proposal: MemoryProposal, *, origin_message: str, run_id: str | None,
                        actor: str, replaces_id: str | None = None) -> str:
        proposal_id = _new_id("prop")
        try:
            with self._lock:
                self._db.execute(
                    "INSERT INTO proposals(id, conversation_id, status, location, category, topic, fact, rationale, "
                    "language, replaces_id, origin_message, origin_run_id, proposed_by, proposed_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (proposal_id, conversation_id, PROPOSAL_PENDING, proposal.location, proposal.category, proposal.topic,
                     proposal.fact, proposal.rationale, proposal.language, replaces_id, origin_message, run_id, actor,
                     _iso(self.now())))
                self._db.commit()
        except sqlite3.IntegrityError as error:
            raise PendingProposalExists(conversation_id) from error
        return proposal_id

    def get_pending(self, conversation_id: str) -> dict | None:
        """La propuesta pendiente de la conversación. Si lleva más de `PENDING_TTL_HOURS` sin respuesta se descarta
        (y queda registrado) en vez de devolverla."""
        with self._lock:
            row = self._db.execute("SELECT * FROM proposals WHERE conversation_id = ? AND status = ?",
                                   (conversation_id, PROPOSAL_PENDING)).fetchone()
        if row is None:
            return None
        proposed_at = datetime.fromisoformat(row["proposed_at"])
        if self.now() - proposed_at > timedelta(hours=PENDING_TTL_HOURS):
            self.resolve_proposal(row["id"], PROPOSAL_DISCARDED, decision="expired_unanswered", decision_message=None,
                                  actor="system:expiry", reason="sin respuesta en 24 h")
            return None
        return dict(row)

    def get_proposal(self, proposal_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
        return dict(row) if row else None

    def resolve_proposal(self, proposal_id: str, status: str, *, decision: str, decision_message: str | None, actor: str,
                         reason: str = "", final_fact: str | None = None, memory_id: str | None = None) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE proposals SET status=?, decision=?, decision_message=?, decided_by=?, decided_at=?, "
                "decision_reason=?, final_fact=?, memory_id=? WHERE id=? AND status=?",
                (status, decision, decision_message, actor, _iso(self.now()), reason, final_fact, memory_id, proposal_id,
                 PROPOSAL_PENDING))
            self._db.commit()

    # --- recuerdos ------------------------------------------------------------------------------------------
    def find_active(self, location: str, category: str, topic: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM memories WHERE location_key=? AND category=? AND topic=? AND status=?",
                (slug(location), category, topic, MEMORY_ACTIVE)).fetchone()
        return dict(row) if row else None

    def activate_memory(self, proposal: dict, fact: str, *, actor: str) -> tuple[str, str | None]:
        """Guarda el recuerdo aprobado. Si ya había uno activo con la misma clave (location + categoría + tema) lo
        marca `superseded` (queda el historial, no se borra). Devuelve `(memory_id, id_sustituido)`."""
        now = self.now()
        memory_id = _new_id("mem")
        ttl = timedelta(days=TTL_DAYS.get(proposal["category"], 180))
        replaced = self.find_active(proposal["location"], proposal["category"], proposal["topic"])
        with self._lock:
            if replaced:
                self._db.execute("UPDATE memories SET status=?, updated_at=? WHERE id=?",
                                 (MEMORY_SUPERSEDED, _iso(now), replaced["id"]))
            self._db.execute(
                "INSERT INTO memories(id, location, location_key, category, topic, fact, language, status, proposal_id, "
                "approved_by, created_at, updated_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (memory_id, proposal["location"], slug(proposal["location"]), proposal["category"], proposal["topic"],
                 fact, proposal["language"], MEMORY_ACTIVE, proposal["id"], actor, _iso(now), _iso(now),
                 _iso(now + ttl)))
            self._db.commit()
        if replaced:
            self.add_event("memory_superseded", actor=actor, conversation_id=proposal["conversation_id"],
                           proposal_id=proposal["id"], memory_id=replaced["id"],
                           detail={"replaced_by": memory_id, "old_fact": replaced["fact"]})
        return memory_id, replaced["id"] if replaced else None

    def active_memories(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM memories WHERE status=? ORDER BY location_key, category, created_at",
                                    (MEMORY_ACTIVE,)).fetchall()
        return [dict(row) for row in rows]

    def count_approvals_since(self, since: datetime, *, conversation_id: str | None = None, actor: str | None = None) -> int:
        clauses, params = ["status IN ('approved','edited')", "decided_at >= ?"], [_iso(since)]
        if conversation_id:
            clauses.append("conversation_id = ?")
            params.append(conversation_id)
        if actor:
            clauses.append("decided_by = ?")
            params.append(actor)
        with self._lock:
            return self._db.execute(f"SELECT COUNT(*) FROM proposals WHERE {' AND '.join(clauses)}", params).fetchone()[0]

    # --- lectura para el agente ------------------------------------------------------------------------------
    def recall(self, question: str, *, k: int = 5, max_chars: int = 1200) -> list[dict]:
        """Recuerdos relevantes para la pregunta, como máximo `k` y `max_chars` caracteres en total.

        Puntuación léxica (no vectorial): la ubicación mencionada pesa más que las palabras del hecho. Con ≤ ~700
        recuerdos activos, escanear es más barato y más predecible que un índice, y evita que «martes» y «miércoles»
        se confundan por similitud semántica. Los caducados no se devuelven."""
        now = self.now()
        question_tokens = {t[:5] for t in re.findall(r"\w+", normalize(question)) if len(t) > 3}
        question_norm = normalize(question)
        scored = []
        for memory in self.active_memories():
            if datetime.fromisoformat(memory["expires_at"]) < now:
                continue
            location_hit = memory["location_key"].replace("_", " ") in question_norm
            haystack = {t[:5] for t in re.findall(r"\w+", normalize(f"{memory['topic']} {memory['fact']}")) if len(t) > 3}
            overlap = len(question_tokens & haystack)
            if not location_hit and overlap < 2:
                continue  # sin ubicación mencionada, exige al menos dos palabras en común: evita ruido
            scored.append((overlap + (3 if location_hit else 0), memory))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["created_at"]), reverse=False)
        selected, used = [], 0
        for _, memory in scored[:k]:
            if used + len(memory["fact"]) > max_chars:
                break
            used += len(memory["fact"])
            selected.append(memory)
        if selected:
            self.touch([memory["id"] for memory in selected])
        return selected

    def touch(self, memory_ids: list[str]) -> None:
        with self._lock:
            self._db.executemany("UPDATE memories SET uses = uses + 1, last_used_at = ? WHERE id = ?",
                                 [(_iso(self.now()), memory_id) for memory_id in memory_ids])
            self._db.commit()

    # --- consolidación y limpieza ----------------------------------------------------------------------------
    def consolidate(self, *, actor: str = "system:consolidation") -> ConsolidationReport:
        """Mantiene la memoria acotada y sin basura. Cuatro reglas, todas auditadas:
        1. caduca lo que pasó su `expires_at` (TTL por categoría);
        2. deduplica hechos idénticos en la misma location + categoría (se queda el más reciente);
        3. limita cada location + categoría a `MAX_PER_BUCKET`, descartando lo más antiguo sin uso reciente;
        4. limita el total a `MAX_ACTIVE_TOTAL` con el mismo criterio."""
        report = ConsolidationReport()
        now = self.now()

        for memory in self.active_memories():
            if datetime.fromisoformat(memory["expires_at"]) < now:
                self._retire(memory, MEMORY_EXPIRED, "memory_expired", actor, "caducó su TTL")
                report.expired += 1

        seen: dict[tuple, dict] = {}
        for memory in sorted(self.active_memories(), key=lambda m: m["created_at"], reverse=True):
            key = (memory["location_key"], memory["category"], normalize(memory["fact"]))
            if key in seen:
                self._retire(memory, MEMORY_SUPERSEDED, "memory_deduplicated", actor, f"duplicado de {seen[key]['id']}")
                report.duplicates += 1
            else:
                seen[key] = memory

        def recency(memory: dict) -> str:
            return memory["last_used_at"] or memory["updated_at"]

        buckets: dict[tuple, list[dict]] = {}
        for memory in self.active_memories():
            buckets.setdefault((memory["location_key"], memory["category"]), []).append(memory)
        for items in buckets.values():
            for memory in sorted(items, key=recency, reverse=True)[MAX_PER_BUCKET:]:
                self._retire(memory, MEMORY_EVICTED, "memory_evicted", actor, f"más de {MAX_PER_BUCKET} en el grupo")
                report.evicted += 1

        remaining = sorted(self.active_memories(), key=recency, reverse=True)
        for memory in remaining[MAX_ACTIVE_TOTAL:]:
            self._retire(memory, MEMORY_EVICTED, "memory_evicted", actor, f"más de {MAX_ACTIVE_TOTAL} en total")
            report.evicted += 1

        with self._lock:
            stale = self._db.execute("SELECT id FROM proposals WHERE status=? AND proposed_at < ?",
                                     (PROPOSAL_PENDING, _iso(now - timedelta(hours=PENDING_TTL_HOURS)))).fetchall()
        for row in stale:
            self.resolve_proposal(row["id"], PROPOSAL_DISCARDED, decision="expired_unanswered", decision_message=None,
                                  actor=actor, reason="sin respuesta en 24 h")
            self.add_event("proposal_discarded", actor=actor, proposal_id=row["id"], detail={"reason": "expired_unanswered"})
            report.pending_discarded += 1
        report.kept = len(self.active_memories())
        return report

    def _retire(self, memory: dict, status: str, event: str, actor: str, reason: str) -> None:
        with self._lock:
            self._db.execute("UPDATE memories SET status=?, updated_at=? WHERE id=?", (status, _iso(self.now()), memory["id"]))
            self._db.commit()
        self.add_event(event, actor=actor, memory_id=memory["id"], proposal_id=memory["proposal_id"],
                       detail={"reason": reason, "fact": memory["fact"]})

    def close(self) -> None:
        with self._lock:
            self._db.close()


assert set(TTL_DAYS) == set(CATEGORIES)  # toda categoría permitida tiene política de caducidad
