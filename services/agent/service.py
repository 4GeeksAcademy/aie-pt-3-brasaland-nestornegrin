"""`AgentService`: compila el grafo una vez y ejecuta corridas con trace y checkpoints.

Una corrida = una pregunta. Cada corrida recibe un `run_id` que sirve a la vez de `thread_id` de los checkpoints de
LangGraph y de nombre del archivo de trace, así que desde un `run_id` se puede reconstruir qué pasó (trace) y en qué
estado quedó el grafo en cada transición (checkpoints).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from functools import lru_cache

from .graph import AgentGraphError, build_checkpointer, build_graph, compile_graph
from .nodes import AgentDependencies, default_dependencies
from .tracing import TraceRecorder, TraceStore, new_run_id

logger = logging.getLogger(__name__)

__all__ = ["AgentExecutionError", "AgentGraphError", "AgentRun", "AgentService", "get_agent_service"]


class AgentExecutionError(RuntimeError):
    """Un nodo falló durante la corrida. `run_id` apunta al trace que quedó guardado (con el nodo que falló)."""

    def __init__(self, run_id: str):
        super().__init__(f"La corrida {run_id} falló")
        self.run_id = run_id


@dataclass(frozen=True)
class AgentRun:
    run_id: str
    answer: str
    status: str
    trace: dict
    conversation_id: str | None = None  # con memoria: el cliente lo reenvía para que su respuesta enlace con la propuesta
    memory: dict | None = None  # {"resolution": ..., "proposal": ...} de este turno (None si no hubo nada de memoria)

    @property
    def sources(self) -> list[str]:
        """Fuentes que se consultaron de verdad, en orden (p. ej. ["tool:tickets", "rag"])."""
        return [item["source"] for item in self.trace.get("sources_used", [])]


def describe_checkpoints(graph, config: dict) -> list[dict]:
    """Checkpoints de la corrida, del primero al último: paso, siguiente nodo y claves del estado en ese momento."""
    snapshots = list(graph.get_state_history(config))
    return [
        {
            "checkpoint_id": snapshot.config["configurable"]["checkpoint_id"],
            "step": snapshot.metadata.get("step"),
            "next": list(snapshot.next),
            "state_keys": sorted(snapshot.values),
        }
        for snapshot in reversed(snapshots)
    ]


class AgentService:
    def __init__(
        self,
        deps: AgentDependencies | None = None,
        *,
        checkpointer=None,
        trace_store: TraceStore | None = None,
    ):
        self.deps = deps or default_dependencies()
        self.checkpointer = checkpointer if checkpointer is not None else build_checkpointer()
        self.trace_store = trace_store or TraceStore()
        self._recorders: dict[str, TraceRecorder] = {}
        # Compilación explícita al crear el servicio: un error estructural aparece al arrancar, no en producción.
        self.graph = compile_graph(build_graph(self.deps, self._recorders.get), self.checkpointer)

    def run(self, question: str, *, conversation_id: str | None = None, actor: str | None = None) -> AgentRun:
        """Una corrida = un mensaje. Con memoria, `conversation_id` enlaza este mensaje con la propuesta pendiente de
        la conversación (si no se da, se crea una nueva) y `actor` es quien lo envía, para el registro de auditoría."""
        run_id = new_run_id()
        recorder = TraceRecorder(run_id, question)
        self._recorders[run_id] = recorder
        config = {"configurable": {"thread_id": run_id}}
        try:
            initial: dict = {"question": question}
            if self.deps.memory is not None:
                conversation_id = conversation_id or f"conv-{uuid.uuid4().hex[:16]}"
                initial.update(conversation_id=conversation_id, actor=actor or "anonymous", run_id=run_id)
            final_state = self.graph.invoke(initial, config)
        except Exception as error:  # noqa: BLE001 - se guarda el trace y se informa con un error propio
            recorder.fail(error, self._checkpoints_or_empty(config))
            self._save(recorder)
            raise AgentExecutionError(run_id) from error
        finally:
            self._recorders.pop(run_id, None)
        recorder.finish(final_state, describe_checkpoints(self.graph, config))
        trace = recorder.to_dict()
        self._save(recorder)
        memory = {key: final_state[state_key] for key, state_key in
                  (("resolution", "memory_resolution"), ("proposal", "memory_proposal")) if final_state.get(state_key)}
        return AgentRun(run_id=run_id, answer=final_state["answer"], status=final_state["status"], trace=trace,
                        conversation_id=conversation_id, memory=memory or None)

    def _checkpoints_or_empty(self, config: dict) -> list[dict]:
        try:
            return describe_checkpoints(self.graph, config)
        except Exception:  # noqa: BLE001 - el trace no debe fallar por no poder leer los checkpoints
            logger.exception("No se pudieron leer los checkpoints de la corrida")
            return []

    def _save(self, recorder: TraceRecorder) -> None:
        try:
            self.trace_store.save(recorder.to_dict())
        except OSError:
            logger.exception("No se pudo guardar el trace de la corrida %s", recorder.run_id)


@lru_cache(maxsize=1)
def get_agent_service() -> AgentService:
    """Servicio compartido por el endpoint (el grafo se compila una sola vez)."""
    return AgentService()
