"""Parte 3 — aprobación humana por departamento (interrupt + checkpointer), arbitraje, límite de rondas, trazabilidad y cierre."""
from __future__ import annotations

import sqlite3
import sys
import threading
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from data.pipelines.rfp_approval import (ApprovalEngine, InMemoryApprovalStore, InvalidDecision, NotReady, STATUS_AWAITING, STATUS_DONE,
                                         thread_id)
from data.pipelines.rfp_approval import config
from rfp_approval_support import OWNERS, ThreePartModel, approve_all, decide, engine_for, seed
from rfp_response_support import BAD_SLA, GOOD
from rfp_support import PDF_INFORMAL

D4 = ("marketing", "operaciones", "procurement", "training")


@pytest.fixture
def env(tmp_path):
    store, model = InMemoryApprovalStore(), ThreePartModel()
    seed(store, model)
    return store, model, engine_for(store, model, tmp_path), tmp_path


def sec(store, ticket=1, dept="marketing"):
    return store.get_part3_input(ticket)["sections"][dept]


# ------------------------------------------------------------------------------------- interrupción y reanudación
def test_start_pauses_every_department_before_approval_and_persists_the_checkpoint(env):
    store, _, engine, _ = env
    assert store.get_part3_input(1)["status"] == "en_evaluación"  # la Parte 2 terminó; nadie ha aprobado nada
    assert engine.start(1) == STATUS_AWAITING == "esperando_aprobación"
    for d in D4:
        assert sec(store, 1, d)["approval_status"] == "pendiente" and sec(store, 1, d)["approval_branch"] == "esperando"
        assert engine.pending(1, d)  # interrupción real en el checkpoint, no solo una bandera en la base de datos
        assert engine.department_graph.get_state(engine._cfg(1, d)).next == ("await_approval",)
    assert store.documents == {}  # nada se genera mientras falten aprobaciones


def test_resume_continues_exactly_where_it_stopped_without_restarting_the_flow(env):
    store, model, engine, _ = env
    engine.start(1)
    generated_before = len(model.part2.agent_calls("generator"))
    assert decide(engine, 1, "marketing") == STATUS_AWAITING
    assert sec(store, 1, "marketing")["approval_status"] == "aprobado" and sec(store, 1, "marketing")["approver"] == "Camila Ospina"
    assert len(model.part2.agent_calls("generator")) == generated_before  # no se regeneró nada: se reanudó, no se reinició
    prepares = [e for e in store.list_events(1) if e["node"] == "awaiting_approval" and e["thread_id"] == "rfp-1:marketing"]
    assert len(prepares) == 1  # `prepare` no se volvió a ejecutar al reanudar


def test_checkpoint_survives_a_restart_of_the_process(env, tmp_path):
    store, model, engine, _ = env
    engine.start(1)
    del engine  # «reinicio»: un motor nuevo, con una conexión nueva al MISMO archivo de checkpoints
    revived = ApprovalEngine(store, model, SqliteSaver(sqlite3.connect(tmp_path / "cp.sqlite", check_same_thread=False)))
    assert revived.pending(1, "operaciones")
    assert decide(revived, 1, "operaciones") == STATUS_AWAITING
    assert sec(store, 1, "operaciones")["approval_status"] == "aprobado"


# ------------------------------------------------------------------------------------- ramas en paralelo
def test_branches_are_launched_in_parallel_not_in_series(tmp_path):
    store, model = InMemoryApprovalStore(), ThreePartModel()
    seed(store, model)
    barrier = threading.Barrier(4, timeout=10)  # solo se cruza si las 4 ramas están EN EJECUCIÓN a la vez
    original = store.approval_update

    def gate(ticket_id, department_id, **fields):
        if fields.get("approval_branch") == "esperando":
            barrier.wait()
        return original(ticket_id, department_id, **fields)

    store.approval_update = gate  # type: ignore[method-assign]
    engine = engine_for(store, model, tmp_path)
    assert engine.start(1) == STATUS_AWAITING  # si fuera en serie, la barrera expiraría y el ticket quedaría en «fallo»
    assert all(sec(store, 1, d)["approval_branch"] == "esperando" for d in D4)


def test_approving_department_b_while_department_a_stays_interrupted(env):
    store, _, engine, _ = env
    engine.start(1)
    decide(engine, 1, "training")
    decide(engine, 1, "procurement")
    # A (marketing) sigue interrumpido: su checkpoint no se tocó y su estado no cambió
    assert engine.pending(1, "marketing") and sec(store, 1, "marketing")["approval_status"] == "pendiente"
    assert sec(store, 1, "training")["approval_status"] == sec(store, 1, "procurement")["approval_status"] == "aprobado"
    assert store.get_part3_input(1)["status"] == STATUS_AWAITING
    events = store.list_events(1)
    decisions = [e["thread_id"] for e in events if e["node"] == "decision"]
    assert decisions == ["rfp-1:training", "rfp-1:procurement"]  # B y C avanzaron mientras A seguía pausado
    assert not any(e["thread_id"] == "rfp-1:marketing" and e["node"] == "decision" for e in events)


def test_approvals_of_two_departments_can_run_at_the_same_time(env):
    store, _, engine, _ = env
    engine.start(1)
    results, errors = {}, []

    def run(dept):
        try:
            results[dept] = decide(engine, 1, dept)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(d,)) for d in ("operaciones", "training", "procurement")]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert not errors
    assert [sec(store, 1, d)["approval_status"] for d in ("operaciones", "training", "procurement")] == ["aprobado"] * 3
    assert engine.pending(1, "marketing")


# ------------------------------------------------------------------------------------- identidad del checkpoint
def test_thread_ids_are_namespaced_by_ticket_and_department(env, tmp_path):
    assert thread_id(7) == "rfp-7" and thread_id(7, "marketing") == "rfp-7:marketing"
    store, model, engine, _ = env
    seed(store, model, PDF_INFORMAL, ticket_id=2)  # un segundo ticket, concurrente, en el mismo almacén y checkpointer
    engine.start(1)
    engine.start(2)
    decide(engine, 1, "marketing")
    assert engine.pending(2, "marketing") and sec(store, 2, "marketing")["approval_status"] == "pendiente"  # el ticket 2 no se movió
    threads = {row[0] for row in sqlite3.connect(tmp_path / "cp.sqlite").execute("select distinct thread_id from checkpoints")}
    assert {"rfp-1", "rfp-1:marketing", "rfp-2:marketing", "rfp-2:procurement"} <= threads
    assert all(t.startswith(("rfp-1", "rfp-2")) for t in threads)


# ------------------------------------------------------------------------------------- validación de la respuesta humana
@pytest.mark.parametrize("raw,code", [
    ({"department_id": "marketing", "action": "approve", "approver": "Felipe Guerrero"}, "approver"),  # no es el responsable
    ({"department_id": "marketing", "action": "aprobar", "approver": "Camila Ospina"}, "schema"),
    ({"department_id": "marketing", "action": "reject", "approver": "Camila Ospina", "comment": "no"}, "schema"),  # sin motivo
    ({"department_id": "ventas", "action": "approve", "approver": "Camila Ospina"}, "department"),
    ({"department_id": "ceo", "action": "approve", "approver": "Mariana Restrepo"}, "not_waiting"),  # aún no le toca a la CEO
    ({"department_id": "marketing", "action": "approve", "approver": "Camila Ospina", "figures": {"x": "mucho"}}, "schema"),
])
def test_invalid_human_response_never_reaches_the_graph(env, raw, code):
    store, _, engine, _ = env
    engine.start(1)
    before = engine.department_graph.get_state(engine._cfg(1, "marketing")).config
    with pytest.raises(InvalidDecision) as exc:
        engine.resume(1, raw)
    assert exc.value.code == code
    assert engine.department_graph.get_state(engine._cfg(1, "marketing")).config == before  # el checkpoint no se tocó
    assert all(sec(store, 1, d)["approval_status"] == "pendiente" for d in D4)


def test_a_department_cannot_decide_twice_and_start_is_gated_by_status(env):
    store, _, engine, _ = env
    assert engine.start(1) == STATUS_AWAITING
    decide(engine, 1, "training")
    with pytest.raises(InvalidDecision) as exc:
        decide(engine, 1, "training")
    assert exc.value.code == "not_waiting"
    fresh = InMemoryApprovalStore()
    fresh.add(9, str(PDF_INFORMAL))
    assert ApprovalEngine(fresh, ThreePartModel(), engine.checkpointer).start(9) == "no_listo"  # no pasó por las Partes 1 y 2


# ------------------------------------------------------------------------------------- rechazo, cambios y límite de rondas
def test_request_changes_returns_only_that_department_to_the_part2_generator(env):
    store, model, engine, _ = env
    engine.start(1)
    calls = {d: len(model.part2.agent_calls("generator", d)) for d in D4}
    decide(engine, 1, "training", "request_changes", "Aclara el plazo de certificación de la receta.")
    assert len(model.part2.agent_calls("generator", "training")) == calls["training"] + 1  # solo ese generador volvió a correr
    assert all(len(model.part2.agent_calls("generator", d)) == calls[d] for d in D4 if d != "training")
    sent = model.part2.agent_calls("generator", "training")[-1][1]["content"]
    assert "REVISIÓN HUMANA" in sent and "Aclara el plazo de certificación" in sent  # el feedback humano llega al generador
    s = sec(store, 1, "training")
    assert s["approval_round"] == 2 and s["approval_status"] == "pendiente" and engine.pending(1, "training")  # nueva interrupción
    assert [h["action"] for h in s["approval_history"]] == ["request_changes"]


def test_reject_is_recorded_and_the_section_goes_back_for_a_new_round(env):
    store, _, engine, _ = env
    engine.start(1)
    decide(engine, 1, "procurement", "reject", "El costo de insumos no está sustentado en la RFP.")
    s = sec(store, 1, "procurement")
    assert s["approval_history"][0]["action"] == "reject" and s["approval_round"] == 2 and engine.pending(1, "procurement")


def test_iteration_limit_is_enforced_in_code_and_escalates_to_the_fixed_arbiter(env, monkeypatch):
    store, model, engine, _ = env
    monkeypatch.setenv("RFP_MAX_APPROVAL_ROUNDS", "2")
    engine.start(1)
    decide(engine, 1, "training", "request_changes", "Falta el tiempo de certificación.")
    assert sec(store, 1, "training")["approval_round"] == 2 and not sec(store, 1, "training")["escalated"]
    generated = len(model.part2.agent_calls("generator", "training"))
    decide(engine, 1, "training", "request_changes", "Sigue faltando el tiempo de certificación.")
    s = sec(store, 1, "training")
    assert s["escalated"] is True and s["approval_round"] == 3  # la ronda 3 ya no es del generador: es del árbitro
    assert len(model.part2.agent_calls("generator", "training")) == generated  # no hay otra vuelta al generador
    escalations = [e for e in store.list_events(1) if e["node"] == "escalated"]
    assert escalations and escalations[-1]["agent"] == "arbiter:Camila Ospina"
    assert engine.pending(1, "training") and engine.department_graph.get_state(engine._cfg(1, "training")).values["packet"]["may_decide"] == ["Camila Ospina", "Jake Morrison"]
    # la dueña del ticket (árbitro fijo) decide: aprueba en nombre del departamento y la rama termina
    engine.resume(1, {"department_id": "training", "action": "approve", "approver": "Camila Ospina", "comment": "Resuelvo como árbitro."})
    s = sec(store, 1, "training")
    assert s["approval_status"] == "aprobado" and s["approver"] == "Camila Ospina" and s["approval_history"][-1]["escalated_decision"] is True
    assert not engine.pending(1, "training")


def test_escalated_rejection_is_final_and_the_ticket_is_never_closed_silently(env, monkeypatch):
    store, _, engine, _ = env
    monkeypatch.setenv("RFP_MAX_APPROVAL_ROUNDS", "1")
    engine.start(1)
    decide(engine, 1, "training", "request_changes", "Falta el tiempo de certificación.")  # ronda 1 = límite → escalada
    assert sec(store, 1, "training")["escalated"] and engine.pending(1, "training")
    engine.resume(1, {"department_id": "training", "action": "reject", "approver": "Camila Ospina", "comment": "Sin esta receta no hay propuesta."})
    s = sec(store, 1, "training")
    assert s["approval_status"] == "rechazado" and not engine.pending(1, "training") and s["approval_branch"] == "libre"
    approve_all(engine, 1, ("marketing", "operaciones", "procurement"))
    decide_state = store.get_part3_input(1)
    assert decide_state["status"] == STATUS_AWAITING and store.documents == {}  # una sección rechazada por el árbitro bloquea el cierre
    asks = [e for e in store.list_events(1) if e["thread_id"] == "rfp-1:training" and e["node"] == "awaiting_approval"]
    assert len(asks) == 2  # ronda normal + una sola pausa para el árbitro: no se relanza en bucle


def test_a_draft_that_breaks_the_sla_cannot_be_approved(env):
    store, _, engine, _ = env
    engine.start(1)
    store.section_update(1, "operaciones", draft_content=sec(store, 1, "operaciones")["draft_content"] + BAD_SLA)
    with pytest.raises(InvalidDecision) as exc:
        decide(engine, 1, "operaciones", "approve")
    assert exc.value.code == "guardrail"


# ------------------------------------------------------------------------------------- arbitraje (BRIEFING §7)
def test_arbiter_setup_sla_breach_forces_changes_before_any_human_sees_it(tmp_path):
    store, model = InMemoryApprovalStore(), ThreePartModel()
    model.part2.drafts["operaciones"] = [GOOD["operaciones"].format(client="Sunset Bay Resorts, LLC") + BAD_SLA] * 3  # agota la Parte 2
    seed(store, model)
    assert sec(store, 1, "operaciones")["needs_human_review"] is True  # llega «provisional»
    engine = engine_for(store, model, tmp_path)
    engine.start(1)
    log = store.get_part3_input(1)["conflicts_log"]
    sla = next(c for c in log if c["trigger_id"] == "setup-sla-breach")
    assert sla["arbiter"] == "Felipe Guerrero" and sla["departments"] == ["operaciones"] and sla["briefing_ref"] == "BRIEFING §7"
    assert sla["status"] == "resuelto"  # el generador corrigió con el feedback del árbitro y el conflicto ya no está en el estado
    s = sec(store, 1, "operaciones")
    assert "5 días hábiles" not in s["draft_content"] and s["approval_history"][0]["action"] == "forced_changes"
    assert "setup-sla-breach" in s["approval_history"][0]["comment"] and "Felipe Guerrero" in s["approval_history"][0]["comment"]
    agents = [e["agent"] for e in store.list_events(1) if e["node"] in ("conflict_detected", "forced_changes")
              and e["input"]["trigger_id"] == "setup-sla-breach"]
    assert agents and set(agents) == {"arbiter:Felipe Guerrero"}  # lo resuelve el árbitro fijo, no un LLM «votando»
    assert not any(e["agent"].startswith("llm") for e in store.list_events(1))


def test_arbiter_cost_vs_feasibility_detected_from_structured_figures(env):
    store, _, engine, _ = env
    engine.start(1)
    decide(engine, 1, "operaciones", "approve", figures={"precio_por_cubierto_usd": "9.50"})
    assert not any(c["trigger_id"] == "cost-vs-feasibility" for c in store.get_part3_input(1)["conflicts_log"])
    decide(engine, 1, "procurement", "approve", figures={"costo_insumos_por_cubierto_usd": "11,20"})
    cost = next(c for c in store.get_part3_input(1)["conflicts_log"] if c["trigger_id"] == "cost-vs-feasibility")
    assert cost["arbiter"] == "Camila Ospina" and cost["departments"] == ["operaciones", "procurement"] and cost["status"] == "abierto"
    assert "Subir precio o reducir alcance" in cost["resolution"]
    for d in ("operaciones", "procurement"):  # request_changes forzado en las secciones desalineadas
        s = sec(store, 1, d)
        assert s["approval_status"] == "pendiente" and s["approval_history"][-1]["action"] == "forced_changes" and engine.pending(1, d)
        assert "cost-vs-feasibility" in s["approval_history"][-1]["comment"]
    decide(engine, 1, "operaciones", "approve", figures={"precio_por_cubierto_usd": "13.00"})  # el humano corrige la cifra → no hay conflicto
    decide(engine, 1, "procurement", "approve")
    assert next(c for c in store.get_part3_input(1)["conflicts_log"] if c["trigger_id"] == "cost-vs-feasibility")["status"] == "resuelto"


def test_arbiter_ceo_threshold_blocks_the_final_document_until_the_ceo_approves(env):
    store, _, engine, _ = env
    engine.start(1)
    assert store.get_part3_input(1)["ceo"]["required"] is True  # Sunset Bay: hasta 75.000 USD/año > 50.000
    approve_all(engine, 1)
    state = store.get_part3_input(1)
    assert state["status"] == STATUS_AWAITING and state["ceo"]["branch"] == "esperando" and store.documents == {}  # bloqueado por la CEO
    assert any(c["trigger_id"] == "ceo-threshold" and c["arbiter"] == "Mariana Restrepo" and c["status"] == "abierto" for c in state["conflicts_log"])
    assert engine.pending(1, "ceo")
    assert decide(engine, 1, "ceo") == STATUS_DONE
    assert any(c["trigger_id"] == "ceo-threshold" and c["status"] == "resuelto" for c in store.get_part3_input(1)["conflicts_log"])


def test_ceo_rejection_sends_the_owner_section_back_and_reopens_the_ceo_after_it(env):
    store, _, engine, _ = env
    engine.start(1)
    approve_all(engine, 1)
    decide(engine, 1, "ceo", "reject", "El valor anual es demasiado alto para el alcance.")
    m = sec(store, 1, "marketing")
    assert m["approval_status"] == "pendiente" and "Mariana Restrepo rechaza" in m["approval_history"][-1]["comment"] and engine.pending(1, "marketing")
    assert store.get_part3_input(1)["status"] == STATUS_AWAITING and store.documents == {}
    assert sec(store, 1, "operaciones")["approval_status"] == "aprobado"  # los demás conservan su aprobación
    decide(engine, 1, "marketing")
    assert engine.pending(1, "ceo") and store.documents == {}
    assert decide(engine, 1, "ceo") == STATUS_DONE


# ------------------------------------------------------------------------------------- cierre: documento final y estados
def test_final_document_is_generated_only_when_everyone_approved_and_ticket_is_terminado(env):
    store, _, engine, _ = env
    engine.start(1)
    approve_all(engine, 1, ("marketing", "operaciones", "procurement"))
    assert store.documents == {} and store.get_part3_input(1)["status"] == STATUS_AWAITING  # falta training (y la CEO)
    decide(engine, 1, "training")
    assert store.documents == {}  # falta la CEO
    assert decide(engine, 1, "ceo") == STATUS_DONE
    doc = store.documents[1]
    assert doc["total_estimated_value"] == 75000 and doc["compliance"]["pass"] is True
    text = doc["content"]
    assert text.startswith("# Propuesta económica — Sunset Bay Resorts, LLC") and "Validez de la oferta:** 30 días" in text
    for d in D4:
        assert sec(store, 1, d)["draft_content"].strip() in text  # consolida exactamente lo aprobado
    assert "| Dirección (CEO) | Mariana Restrepo |" in text and store.get_part3_input(1)["completed_at"]


def test_informal_rfp_without_ceo_threshold_closes_with_only_department_approvals(tmp_path):
    store, model = InMemoryApprovalStore(), ThreePartModel()
    seed(store, model, PDF_INFORMAL)
    engine = engine_for(store, model, tmp_path)
    engine.start(1)
    assert store.get_part3_input(1)["ceo"]["required"] is False  # sin presupuesto en la RFP no hay umbral de CEO que aplicar
    assert not any(c["trigger_id"] == "ceo-threshold" for c in store.get_part3_input(1)["conflicts_log"])
    approve_all(engine, 1, ("marketing", "operaciones", "procurement"))
    assert store.get_part3_input(1)["status"] == STATUS_DONE and 1 in store.documents
    assert "Training y Estándares de Calidad" not in store.documents[1]["content"]  # solo los departamentos activos


def test_synthesis_runs_once_even_if_the_last_two_approvals_race(env):
    store, _, engine, _ = env
    engine.start(1)
    approve_all(engine, 1, ("marketing", "operaciones"))
    saved = []
    original = store.save_final_document
    store.save_final_document = lambda t, d: (saved.append(t), original(t, d))[1]  # type: ignore[method-assign]
    threads = [threading.Thread(target=decide, args=(engine, 1, d)) for d in ("procurement", "training")]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    decide(engine, 1, "ceo")
    assert saved == [1] and store.get_part3_input(1)["status"] == STATUS_DONE


# ------------------------------------------------------------------------------------- trazabilidad
def test_every_node_run_is_traced_with_agent_input_output_and_timestamp_in_order(env):
    store, _, engine, _ = env
    engine.start(1)
    approve_all(engine, 1)
    decide(engine, 1, "ceo")
    events = store.list_events(1)
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    for e in events:
        assert e["agent"] and e["node"] and e["ts"] and "input" in e and "output" in e and e["part"] in (1, 2, 3)
    stamps = [e["ts"] for e in events]
    assert stamps == sorted(stamps)  # el orden de ejecución es el orden de los eventos
    parts = [e["part"] for e in events]
    assert parts == sorted(parts)  # primero la Parte 1, luego la 2, luego la 3: un solo proceso
    nodes = [(e["part"], e["node"]) for e in events]
    assert nodes.index((1, "classify")) < nodes.index((2, "generate")) < nodes.index((3, "open")) < nodes.index((3, "synthesize"))
    assert {"classifier", "orchestrator", "synthesizer", "ultimate-synthesizer", "approval-orchestrator"} <= {e["agent"] for e in events}
    assert any(e["agent"] == "human:Camila Ospina" and e["node"] == "decision" and e["output"]["action"] == "approve" for e in events)
    assert any(e["agent"] == "generator:operaciones" for e in events) and any(e["agent"].startswith("evaluator-compliance:") for e in events)
    assert all("%PDF" not in str(e) for e in events)  # el documento completo no se vuelca en la traza (solo resúmenes)


def test_trace_is_also_kept_in_the_graph_state(env):
    _, _, engine, _ = env
    engine.start(1)
    state = engine.department_graph.get_state(engine._cfg(1, "marketing")).values
    assert state["trace"] and state["trace"][0]["agent"] == "human:Camila Ospina" and state["trace"][0]["node"] == "awaiting_approval"


# ------------------------------------------------------------------------------------- una prueba de punta a punta
def test_end_to_end_three_parts_without_state_jumps(tmp_path):
    store, model = InMemoryApprovalStore(), ThreePartModel()
    seed(store, model)
    engine = engine_for(store, model, tmp_path)
    engine.start(1)
    decide(engine, 1, "training", "request_changes", "Indica quién certifica la receta de autor.")  # una vuelta al generador
    approve_all(engine, 1)
    decide(engine, 1, "ceo")
    assert [s for _, s in store.status_log] == ["generando_borrador", "en_evaluación", "esperando_aprobación", "terminado"]
    assert store.get_part3_input(1)["status"] == "terminado"
    # el cliente, el RFP y las cifras llegan intactos desde la Parte 1 hasta el documento final
    assert "SBR-2026-0417" in store.documents[1]["content"] and "Sunset Bay Resorts, LLC" in store.documents[1]["content"]
    with pytest.raises(InvalidDecision):
        decide(engine, 1, "marketing")  # ticket terminado: ya no acepta decisiones
    assert engine.start(1) == "no_listo"  # ni se reabre


# ------------------------------------------------------------------------------------- script E2E reproducible
@pytest.mark.parametrize("pdf,ceo", [(None, True), (PDF_INFORMAL, False)])
def test_reproducible_e2e_script_runs_the_three_parts_with_simulated_resumes(tmp_path, pdf, ceo):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.rfp_e2e import run

    lines: list[str] = []
    result = run(pdf, checkpoint_dir=tmp_path, out=lines.append)
    assert result["status"] == "terminado" and result["document"]["content"].startswith("# Propuesta económica")
    assert any("(ceo)" in line for line in lines) is ceo  # la CEO solo interviene por encima de 50.000 USD/año
    actions = [(s["department"], s["action"]) for s in result["steps"]]
    assert (("training", "request_changes") in actions) is (pdf is None)  # RFP formal: training vuelve una vez a su generador; la informal no tiene training
    nodes = [(e["part"], e["node"]) for e in result["events"]]
    assert nodes.index((1, "synthesize")) < nodes.index((2, "load")) < nodes.index((3, "open")) < nodes.index((3, "close"))
    assert all(p == 1 for p, _ in nodes[:nodes.index((2, "load"))])  # la Parte 1 termina entera antes de que empiece la 2
    # la vuelta de training al generador (ciclo de la Parte 2) ocurre DURANTE la Parte 3 y queda en la traza, con su agente
    assert (any(e["agent"] == "generator:training" and e["node"] == "regenerate" for e in result["events"])) is (pdf is None)
    assert result["steps"][-1]["ticket_status"] == "terminado" and all(s["ticket_status"] == "esperando_aprobación" for s in result["steps"][:-1])
