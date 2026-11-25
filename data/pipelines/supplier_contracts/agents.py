"""Identidad y permisos de los agentes. Cada agente tiene SU identidad y solo puede usar SUS herramientas (config.AGENT_PERMISSIONS);
cualquier otra herramienta se deniega y queda registrada. Cada llamada a una herramienta deja un evento con el agente que la hizo."""
from __future__ import annotations

from typing import Callable

from . import config
from .store import Store


class PermissionDenied(Exception):
    pass


class BudgetExceeded(Exception):
    pass


class Toolbox:
    """Caja de herramientas de UN agente. `use` es la única puerta: comprueba permiso, ejecuta y registra quién lo hizo."""

    def __init__(self, store: Store, agent_id: str, request_id: str):
        if agent_id not in config.AGENT_PERMISSIONS:
            raise PermissionDenied(f"agente desconocido: {agent_id}")
        self.store, self.agent_id, self.request_id = store, agent_id, request_id

    def use(self, tool: str, subject: str, fn: Callable, detail: dict | None = None):
        if tool in config.FORBIDDEN_FOR_AGENTS or tool not in config.AGENT_PERMISSIONS[self.agent_id]:
            self.store.event("agent", self.agent_id, "denied", subject, {"tool": tool, "request": self.request_id})
            raise PermissionDenied(f"{self.agent_id} no tiene la herramienta «{tool}»")
        result = fn()
        self.store.event("agent", self.agent_id, f"tool:{tool}", subject, {"request": self.request_id, **(detail or {})})
        return result


class ConsultBudget:
    """Tope de consultas del supervisor por petición: evita bucles y costes sin control."""

    def __init__(self, limit: int = config.MAX_CONSULTS_PER_REQUEST):
        self.limit, self.used = limit, 0

    def take(self) -> None:
        if self.used >= self.limit:
            raise BudgetExceeded(f"límite de {self.limit} consultas por petición alcanzado")
        self.used += 1
