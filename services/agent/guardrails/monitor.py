"""Observabilidad: cada bloqueo o redirección de un guardrail queda registrado con su TIPO de fallo
(estructural / de contenido / de seguridad) y se puede resumir cuántas veces disparó cada uno.

Dos destinos: contadores en memoria (endpoint `GET /agent/guardrails/summary`, sesión de prueba actual) y un archivo JSONL
(`data/logs/agent-guardrails.jsonl`, o `AGENT_GUARDRAILS_LOG`), que lee el comando `python -m services.agent.guardrails summary`
aunque el servicio ya no esté corriendo. Nunca se registra el mensaje completo: solo un extracto sin correos ni teléfonos.
"""
from __future__ import annotations

import json
import os
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOG = Path("data/logs/agent-guardrails.jsonl")
KINDS = ("seguridad", "contenido", "estructural")


def log_path() -> Path:
    return Path(os.environ.get("AGENT_GUARDRAILS_LOG") or DEFAULT_LOG)


def summarize(events: list[dict]) -> dict:
    by = {name: Counter(e.get(name) for e in events) for name in ("kind", "guardrail", "reason", "action")}
    return {
        "total": len(events),
        "by_failure_type": {kind: by["kind"].get(kind, 0) for kind in KINDS},
        "by_guardrail": dict(by["guardrail"].most_common()),
        "by_reason": dict(by["reason"].most_common()),
        "by_action": dict(by["action"].most_common()),
    }


class GuardrailMonitor:
    def __init__(self, path: Path | str | None = None, *, write_file: bool = True):
        self._path = Path(path) if path else None
        self._write_file = write_file
        self._events: list[dict] = []
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path or log_path()

    def record(self, event: dict, *, conversation_id: str | None = None, run_id: str | None = None, excerpt: str = "") -> dict:
        entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **event,
                 "conversation_id": conversation_id, "run_id": run_id, "excerpt": excerpt[:120]}
        with self._lock:
            self._events.append(entry)
            if self._write_file:
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with self.path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
                except OSError:  # el registro no debe tumbar la respuesta
                    pass
        return entry

    def events(self) -> list[dict]:
        with self._lock:
            return list(self._events)

    def summary(self) -> dict:
        return summarize(self.events())

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


def read_log(path: Path | str | None = None) -> list[dict]:
    target = Path(path) if path else log_path()
    if not target.exists():
        return []
    events = []
    for line in target.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events
