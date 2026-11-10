"""Evidencia del Hito 8 (Parte 1): dos ciclos completos del flujo de memoria sobre el grafo REAL y el almacén REAL.

Ciclo A: la actualización se aprueba y se refleja en una interacción futura (otra conversación).
Ciclo B: la actualización se rechaza y la memoria permanece sin cambios.

Con `AGENT_MEMORY_EVIDENCE=docs/agent/memory-evidence.md` el test escribe el relato de ambos ciclos (mensajes, respuestas,
estado de la memoria y registro de auditoría). El modelo y el clasificador son los guionizados de `memory_support.py`:
esto prueba el FLUJO; las corridas con el modelo real están en docs/agent/memory.md (sección «Cómo reproducirlo»).
"""
from __future__ import annotations

import os
from pathlib import Path

from memory_support import MIAMI_FACT, MIAMI_FIX, SCRIPT, SUPPLIER_FACT, SUPPLIER_FIX, MemoryAgent

LINES: list[str] = []


def turn(agent: MemoryAgent, conversation: str, user: str, message: str):
    agent.clock.advance(minutes=2)  # los mensajes reales no llegan en el mismo segundo
    run = agent.say(message, conversation=conversation, user=user)
    LINES.extend([f"**{user}** (`{conversation}`): {message}", "", "**Agente** (estado `" + run.status + "`):", "",
                  *[f"> {line}" if line else ">" for line in run.answer.splitlines()], ""])
    return run


def memory_state(agent: MemoryAgent) -> None:
    facts = agent.active_facts()
    LINES.extend(["Memoria activa:" + (" `(vacía)`" if not facts else ""), "", *[f"- {fact}" for fact in facts],
                  *([""] if facts else [])])


def audit(agent: MemoryAgent, conversation_ids: list[str]) -> None:
    LINES.extend(["| # | Momento (UTC) | Evento | Actor | Detalle |", "|---|---|---|---|---|"])
    for event in agent.store.events():
        if event["conversation_id"] not in conversation_ids and event["conversation_id"] is not None:
            continue
        detail = event["detail"] or {}
        shown = {k: v for k, v in detail.items() if k in ("fact", "intent", "confidence", "decision_message", "reason")}
        LINES.append(f"| {event['seq']} | {event['ts']} | `{event['event']}` | {event['actor']} | "
                     f"{'; '.join(f'{k}={v}' for k, v in shown.items())} |")
    LINES.append("")


def test_two_complete_cycles_one_approved_one_rejected(tmp_path):
    agent = MemoryAgent(tmp_path, SCRIPT)
    LINES.extend(["# Evidencia — memoria del agente (Hito 8, Parte 1)", "",
                  "Generado por `tests/pipelines/test_agent_memory_evidence.py` sobre el grafo y el almacén reales; "
                  "el modelo y el clasificador son los guionizados de `memory_support.py` (flujo, no calidad del modelo).", "",
                  "## Ciclo A — la actualización se APRUEBA y se refleja después", ""])

    first = turn(agent, "conv-ciclo-a1", "carlos.jimenez", SUPPLIER_FIX)
    assert "¿Quieres que recuerde esto para la próxima vez?" in first.answer and SUPPLIER_FACT in first.answer
    LINES.extend(["Tras la propuesta, aún nada guardado (solo hay una propuesta pendiente):", ""])
    memory_state(agent)
    assert agent.active_facts() == []

    approval = turn(agent, "conv-ciclo-a1", "carlos.jimenez", "Sí, guárdalo")
    assert approval.status == "memory_decision"
    memory_state(agent)
    assert agent.active_facts() == [SUPPLIER_FACT]

    LINES.extend(["Más tarde, en OTRA conversación, el agente ya lo sabe:", ""])
    later = turn(agent, "conv-ciclo-a2", "carlos.jimenez", "¿Qué día entrega el proveedor de vegetales de Medellín?")
    assert SUPPLIER_FACT in later.answer

    LINES.extend(["## Ciclo B — la actualización se RECHAZA y la memoria no cambia", ""])
    before = agent.active_facts()
    LINES.extend(["Memoria antes del ciclo:", ""])
    memory_state(agent)
    turn(agent, "conv-ciclo-b1", "ashley.r", MIAMI_FIX)
    refusal = turn(agent, "conv-ciclo-b1", "ashley.r", "No, no lo guardes")
    assert "no lo guardo" in refusal.answer
    LINES.extend(["Memoria después del rechazo (idéntica):", ""])
    memory_state(agent)
    assert agent.active_facts() == before and MIAMI_FACT not in agent.active_facts()
    turn(agent, "conv-ciclo-b2", "ashley.r", "¿A qué hora cierra Miami Beach los fines de semana?")
    assert agent.model.calls[-1][2] == []  # lo rechazado no llega al modelo

    LINES.extend(["## Registro de auditoría (solo-añadir)", "",
                  "Cada propuesta y su resultado, aprobada o rechazada, con quién la autorizó y cuándo:", ""])
    audit(agent, ["conv-ciclo-a1", "conv-ciclo-a2", "conv-ciclo-b1", "conv-ciclo-b2"])
    proposals = agent.store._db.execute("SELECT status, fact, proposed_at, decided_by, decided_at FROM proposals ORDER BY proposed_at").fetchall()
    assert [row["status"] for row in proposals] == ["approved", "rejected"]
    assert all(row["decided_by"] and row["decided_at"] for row in proposals)

    target = os.environ.get("AGENT_MEMORY_EVIDENCE")
    if target:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_text("\n".join(LINES) + "\n", encoding="utf-8")
