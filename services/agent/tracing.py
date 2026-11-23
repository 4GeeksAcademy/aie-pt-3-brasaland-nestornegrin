"""Trace consultable de cada corrida del agente.

Cada corrida deja un archivo JSON (`<run_id>.json`) con la pregunta, los nodos que se ejecutaron, en qué orden, qué
recibió y qué produjo cada uno, cuánto tardó, los checkpoints de LangGraph y el resultado final. Se escribe aunque la
corrida falle (con el nodo que falló), y se puede leer después con `TraceStore.load(run_id)` o abrir el archivo.

Para no inflar el trace con texto de los documentos, el contexto recuperado se resume como referencias
(documento, sección y número de chunk): lo que importa para explicar una respuesta es QUÉ se recuperó, y el texto
completo ya está en la base de conocimiento.

Desde la Parte 2 el trace dice además QUÉ FUENTES se usaron y en qué orden: `route` (lo que decidió el enrutador y por
qué) y `sources_used` (cada fuente que de verdad se consultó, en orden de ejecución: `tool:tickets`, `tool:inventory`
y/o `rag`, con su resultado), sin tener que deducirlo de los pasos.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .nodes import NODE_BY_SOURCE, NODE_RETRIEVE, NODE_ROUTE

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TRACE_DIR = REPO_ROOT / "data" / "traces" / "agent"
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_run_id() -> str:
    return f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"


def chunk_reference(chunk: dict) -> dict:
    return {
        "source_document": chunk.get("source_document"),
        "section": chunk.get("section"),
        "chunk_index": chunk.get("chunk_index"),
    }


def summarize(values: dict | None) -> dict | None:
    """Versión legible y pequeña de un estado o de la actualización que devuelve un nodo."""
    if values is None:
        return None
    summary: dict[str, Any] = {}
    for key, value in values.items():
        if key == "context":
            summary["context"] = [chunk_reference(chunk) for chunk in (value or [])]
        else:
            summary[key] = value
    return summary


class TraceRecorder:
    """Acumula los pasos de UNA corrida. Lo usa el envoltorio `traced_node` y lo cierra `AgentService`."""

    def __init__(self, run_id: str, question: Any):
        self.run_id = run_id
        self.question = question
        self.started_at = utc_now()
        self._t0 = time.perf_counter()
        self.steps: list[dict] = []
        self.checkpoints: list[dict] = []
        self.final_state: dict | None = None
        self.status = "running"
        self.error: dict | None = None
        self.finished_at: str | None = None
        self.duration_ms: float | None = None

    def run_step(self, node: str, state: dict, node_fn: Callable[[dict], dict]) -> dict:
        step = {
            "order": len(self.steps) + 1,
            "node": node,
            "started_at": utc_now(),
            "input": summarize(dict(state)),
            "output": None,
            "error": None,
        }
        self.steps.append(step)
        t0 = time.perf_counter()
        try:
            update = node_fn(state)
        except Exception as error:  # noqa: BLE001 - se anota en el trace y se vuelve a lanzar
            step["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            step["duration_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        step["output"] = summarize(update)
        return update

    def finish(self, final_state: dict, checkpoints: list[dict]) -> None:
        self.final_state = summarize(dict(final_state))
        self.status = final_state.get("status", "unknown")
        self.checkpoints = checkpoints
        self._close()

    def fail(self, error: Exception, checkpoints: list[dict] | None = None) -> None:
        self.status = "error"
        self.error = {"type": type(error).__name__, "message": str(error)}
        self.checkpoints = checkpoints or []
        self._close()

    def _close(self) -> None:
        self.finished_at = utc_now()
        self.duration_ms = round((time.perf_counter() - self._t0) * 1000, 3)

    def route(self) -> dict | None:
        step = next((step for step in self.steps if step["node"] == NODE_ROUTE), None)
        return ((step or {}).get("output") or {}).get("route")

    def sources_used(self) -> list[dict]:
        """Fuentes consultadas, en el orden en que se ejecutaron (RAG y/o tools, con su resultado)."""
        labels = {node: ("rag" if source == "rag" else f"tool:{source}") for source, node in NODE_BY_SOURCE.items()}
        used = []
        for step in self.steps:
            label = labels.get(step["node"])
            if label is None:
                continue
            output = step.get("output") or {}
            if step["node"] == NODE_RETRIEVE:
                detail = {"chunks": len(output.get("context", [])), "error": step["error"]}
            else:
                last = (output.get("tool_results") or [{}])[-1]
                detail = {"outcome": last.get("outcome"), "error": step["error"]}
            used.append({"source": label, "node": step["node"], "order": step["order"], **detail})
        return used

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "question": self.question,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "node_order": [step["node"] for step in self.steps],
            "route": self.route(),
            "sources_used": self.sources_used(),
            "steps": self.steps,
            "checkpoints": self.checkpoints,
            "final_state": self.final_state,
            "error": self.error,
        }


def traced_node(
    node_name: str,
    node_fn: Callable[[dict], dict],
    recorder_for: Callable[[str], TraceRecorder | None],
):
    """Envuelve un nodo para que cada ejecución quede en el trace de su corrida (la identifica el `thread_id`)."""
    from langchain_core.runnables import RunnableConfig

    def wrapper(state: dict, config: RunnableConfig) -> dict:
        thread_id = (config.get("configurable") or {}).get("thread_id")
        recorder = recorder_for(thread_id) if thread_id else None
        return node_fn(state) if recorder is None else recorder.run_step(node_name, state, node_fn)

    wrapper.__name__ = node_name
    return wrapper


class TraceStore:
    """Guarda y lee traces como archivos JSON (uno por corrida) en un directorio."""

    def __init__(self, directory: Path | str | None = None):
        configured = os.environ.get("AGENT_TRACE_DIR")
        self.directory = Path(directory or configured or DEFAULT_TRACE_DIR)

    def path_for(self, run_id: str) -> Path:
        if not _RUN_ID_PATTERN.match(run_id):
            raise ValueError(f"run_id no válido: {run_id!r}")
        return self.directory / f"{run_id}.json"

    def save(self, trace: dict) -> Path:
        path = self.path_for(trace["run_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return path

    def load(self, run_id: str) -> dict:
        return json.loads(self.path_for(run_id).read_text(encoding="utf-8"))

    def list_runs(self) -> list[str]:
        if not self.directory.exists():
            return []
        return sorted(path.stem for path in self.directory.glob("*.json"))
