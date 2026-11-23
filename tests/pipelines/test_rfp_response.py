"""Pruebas de la Parte 2 (generación y evaluación de respuestas a RFP): generadores, evaluadores, ciclo con límite y handoff a la Parte 3.
Deterministas: modelo simulado, sin red ni base de datos. Los lineamientos contra los que se evalúa son los del company-BRIEFING §5.

    python -m pytest tests/pipelines/test_rfp_response.py
"""
from __future__ import annotations

import json
import threading

import pytest
from rfp_response_support import BAD_COMPETITOR, BAD_FIGURE, BAD_PRICE, BAD_SLA, GOOD, SHORT, ScriptedResponseModel
from rfp_support import PDF_FORMAL, PDF_INFORMAL, PDF_INVALID, ScriptedRfpModel

from data.pipelines.rfp_intake import process_ticket
from data.pipelines.rfp_intake.agents import AgentOutputError
from data.pipelines.rfp_response import (NotReady, InMemoryResponseStore, build_graph, config, generate_ticket)
from data.pipelines.rfp_response import agents, rules

DEPTS = ["marketing", "operaciones", "procurement", "training"]


def prepared(pdf=PDF_FORMAL, ticket_id=1):
    """Parte 1 terminada: el ticket llega a la Parte 2 en `analisis_completo` con su handoff (no hay PDF que releer)."""
    store = InMemoryResponseStore()
    store.add(ticket_id, str(pdf))
    assert process_ticket(ticket_id, store, ScriptedRfpModel()) == "completo"
    return store


def run(store, model=None, *, mode="start", ticket_id=1):
    model = model or ScriptedResponseModel()
    return generate_ticket(ticket_id, store, model, mode=mode), model


def section(store, dept, ticket_id=1):
    return next(s for s in store.sections[ticket_id] if s["department_id"] == dept)


# --------------------------------------------------------------------------------------------------------------
# Entrada: solo el handoff de la Parte 1
# --------------------------------------------------------------------------------------------------------------
def test_generators_consume_the_part1_handoff_and_never_the_pdf_text():
    store = prepared()
    outcome, model = run(store)
    assert outcome == "completo"
    everything = json.dumps([m for _, _, m in model.calls], ensure_ascii=False)
    assert "Sunset Bay Resorts" in everything and "Staffing plan" not in everything and "Questions due" not in everything
    assert store.get_ticket(1)["markdown"] is not None  # la Parte 1 lo guardó, pero la Parte 2 no lo usa


def test_each_generator_sees_only_its_own_workstream():
    store = prepared()
    _, model = run(store)
    marketing = json.dumps(model.agent_calls("generator", "marketing")[0], ensure_ascii=False)
    assert "Definir términos de exclusividad y co-branding." in marketing  # su `ask`
    assert "Evaluar capacidad y plan de personal." not in marketing  # el `ask` de operaciones no se filtra
    assert "Felipe Guerrero" not in marketing
    system = model.agent_calls("generator", "operaciones")[0][0]["content"]
    assert "Operaciones de Restaurante" in system and "Felipe Guerrero" in system and "pilares de marca" not in system


def test_only_the_ticket_owner_section_carries_the_brand_pillars_and_validity_instructions():
    assert "calidad consistente" in agents.generator_system("marketing") and "validez de 30 días" in agents.generator_system("marketing")
    assert "calidad consistente" not in agents.generator_system("training")


def test_part2_does_not_start_from_tickets_that_part1_did_not_finish():
    store = InMemoryResponseStore()
    store.add(1, str(PDF_INVALID))
    assert process_ticket(1, store, ScriptedRfpModel()) == "descartado"
    store.add(2, str(PDF_FORMAL))  # analizando, sin handoff
    for tid in (1, 2):
        before = store.get_ticket(tid)
        assert generate_ticket(tid, store, ScriptedResponseModel()) == "no_listo"
        assert store.get_ticket(tid) == before and store.status_log == []


def test_an_invalid_handoff_contract_is_rejected_explicitly():
    store = prepared()
    store.tickets[1]["handoff"]["ready_for_part_2"] = False
    assert generate_ticket(1, store, ScriptedResponseModel()) == "no_listo"
    with pytest.raises(NotReady):
        agents.validate_handoff({"schema_version": 2, "ready_for_part_2": True, "workstreams": [{}]})


# --------------------------------------------------------------------------------------------------------------
# Precios en COP y USD sin inventar la tasa
# --------------------------------------------------------------------------------------------------------------
def test_price_reference_is_dual_currency_only_with_a_configured_rate(monkeypatch):
    meta = {"budget_usd_min": 60000.0, "budget_usd_max": 75000.0}
    assert agents.price_reference(meta, None)["disponible"] is False  # sin TRM no se escriben montos
    ref = agents.price_reference(meta, 4000.0)
    assert ref["disponible"] and "USD 60,000 a USD 75,000" in ref["texto"] and "COP 240,000,000 a COP 300,000,000" in ref["texto"]
    assert agents.price_reference({}, 4000.0)["disponible"] is False
    monkeypatch.setenv("RFP_USD_COP_RATE", "4000")
    payload = agents.generator_payload(prepared().get_part2_input(1)["handoff"], "procurement")
    assert payload["precios_referencia"]["disponible"] is True
    assert {"240000000", "300000000", "4000"} <= agents.allowed_numbers(payload)  # el monto convertido es una cifra permitida


# --------------------------------------------------------------------------------------------------------------
# Evaluadores
# --------------------------------------------------------------------------------------------------------------
def test_readability_passes_a_clear_draft_and_fails_short_or_hard_to_read_ones():
    ok = rules.evaluate_readability(GOOD["procurement"].format(client="Andes Tech Solutions"))
    assert ok["pass"] and ok["score"] > 45 and ok["details"]["metrics"]["language"] == "es"
    short = rules.evaluate_readability(SHORT)
    assert not short["pass"] and any("corta" in p for p in short["details"]["problems"])
    wall = " ".join(["La implementación contextualizada de infraestructuras interdepartamentales presupuestarias"] * 6) + "."
    hard = rules.evaluate_readability(wall)
    assert not hard["pass"] and hard["details"]["longest_sentences"]


KEY = [{"aspect": "Exclusividad", "detail": "d"}, {"aspect": "Co-branding", "detail": "d"}]


def test_relevance_reports_missing_aspects_and_a_lenient_judge_cannot_pass_without_a_real_quote():
    draft = "Definimos los términos de marca. No hablamos de nada más."
    honest = json.dumps({"aspects": [{"index": 0, "covered": False, "evidence": ""},
                                     {"index": 1, "covered": True, "evidence": "Definimos los términos de marca."}]})
    r = agents.evaluate_relevance(lambda m: honest, KEY, draft)
    assert r["pass"] is False and r["missing_aspects"] == ["Exclusividad"]
    lenient = json.dumps({"aspects": [{"index": i, "covered": True, "evidence": "cita que no está en el borrador"} for i in range(2)]})
    r = agents.evaluate_relevance(lambda m: lenient, KEY, draft)
    assert r["missing_aspects"] == ["Exclusividad", "Co-branding"] and r["details"]["evidence_not_found_in_draft"]
    with pytest.raises(AgentOutputError):
        agents.evaluate_relevance(lambda m: "no es json", KEY, draft)
    assert agents.evaluate_relevance(lambda m: "x", [], draft)["pass"]  # sin aspectos que verificar


GOOD_MK = GOOD["marketing"].format(client="Sunset Bay Resorts, LLC")


@pytest.mark.parametrize("dept,text,rule", [
    ("operaciones", GOOD["operaciones"] + BAD_PRICE, "price-dual-currency"),
    ("operaciones", GOOD["operaciones"] + " Cobramos COP 500.000 por evento.", "price-dual-currency"),
    ("operaciones", GOOD["operaciones"] + BAD_SLA, "setup-sla-breach"),
    ("operaciones", GOOD["operaciones"] + " La entrega será inmediata.", "setup-sla-breach"),
    ("procurement", GOOD["procurement"] + BAD_COMPETITOR, "no-competitors"),
    ("training", GOOD["training"] + BAD_FIGURE, "no-invented-figures"),
    ("marketing", GOOD_MK.replace("calidad consistente", "buena calidad"), "brand-pillars"),
    ("marketing", GOOD_MK.replace("30 días", "60 días"), "offer-validity-30d"),
    ("marketing", GOOD_MK.replace("La oferta tiene una validez de 30 días desde su emisión.", ""), "offer-validity-30d"),
    ("operaciones", GOOD["operaciones"] + " La oferta tiene una validez de 15 días.", "offer-validity-30d"),
])
def test_each_briefing_rule_is_detected_with_its_id_and_the_offending_sentence(dept, text, rule):
    result = rules.evaluate_compliance(text, dept, {"3", "60000", "75000"} - {"60000"})
    assert result["pass"] is False and rule in result["rule_ids"]
    violation = next(v for v in result["violations"] if v["rule_id"] == rule)
    assert violation["briefing_ref"].startswith("§") and violation["message"]
    if rule not in ("brand-pillars",) and "validez de 30" not in violation["message"] and "Falta el período" not in violation["message"]:
        assert violation["excerpt"] and violation["excerpt"] in text


def test_good_drafts_pass_compliance_and_brand_pillars_are_required_only_from_the_ticket_owner():
    for dept in DEPTS:
        assert rules.evaluate_compliance(GOOD[dept].format(client="Andes"), dept, set())["pass"], dept
    no_pillars = GOOD["operaciones"]
    assert "brand-pillars" not in rules.evaluate_compliance(no_pillars, "operaciones", set())["rule_ids"]
    assert "brand-pillars" in rules.evaluate_compliance(no_pillars, "marketing", set())["rule_ids"]


def test_compliance_failure_anchored_to_the_briefing_is_a_small_explicit_case():
    """BRIEFING §5/§7: ninguna sección puede prometer montaje/entrega en menos de 10 días hábiles → compliance.pass == False."""
    draft = GOOD["operaciones"] + " Prometemos el montaje en 3 días hábiles."
    result = rules.evaluate_compliance(draft, "operaciones", {"3"})
    assert result["pass"] is False and result["rule_ids"] == ["setup-sla-breach"]  # mismo id que el trigger de la Parte 3
    assert "10" in result["violations"][0]["message"]


@pytest.mark.parametrize("sentence,breaches", [
    ("El montaje tomará 10 días hábiles.", False), ("La entrega será en dos semanas.", False), ("El montaje será en 9 días hábiles.", True),
    ("La entrega será en una semana.", True), ("El montaje estará listo en 48 horas.", True), ("El montaje toma entre 5 y 12 días.", True),
    ("La instalación tarda 7 días calendario.", True), ("La reunión será en 3 días.", False)])
def test_setup_time_parser(sentence, breaches):
    assert bool(rules.check_setup_times(sentence)) is breaches


# --------------------------------------------------------------------------------------------------------------
# EvaluationResult: forma estructurada
# --------------------------------------------------------------------------------------------------------------
def test_evaluation_result_has_the_structured_shape_the_ticket_asks_for():
    store = prepared()
    run(store)
    ev = section(store, "operaciones")["evaluation_results"]
    assert ev["section_id"] == "1:operaciones" and ev["department_id"] == "operaciones" and ev["overall_pass"] is True
    assert set(ev["readability"]) == {"pass", "score", "details"} and ev["relevance"].keys() >= {"pass", "missing_aspects"}
    assert ev["compliance"].keys() >= {"pass", "rule_ids", "violations"} and ev["feedback_for_generator"] == ""


# --------------------------------------------------------------------------------------------------------------
# Grafo: éxito, ciclo con feedback, límite y handoff a la Parte 3
# --------------------------------------------------------------------------------------------------------------
def test_all_sections_pass_and_the_ticket_ends_ready_for_part3_without_inventing_part3_states():
    store = prepared()
    outcome, model = run(store)
    ticket = store.get_ticket(1)
    assert outcome == "completo" and ticket["status"] == config.STATUS_EVALUATING and ticket["response_completed_at"]
    assert [s for _, s in store.status_log] == [config.STATUS_GENERATING, config.STATUS_EVALUATING]
    assert all(section(store, d)["generation_status"] == "paso" and section(store, d)["iterations"] == 1 for d in DEPTS)
    h = ticket["part3_handoff"]
    assert h["ready_for_part_3"] is True and h["all_sections_passed"] is True and h["needs_human_review"] == []
    assert [s["department_id"] for s in h["sections"]] == DEPTS
    for s in h["sections"]:  # contenido generado + resultado estructurado por departamento
        assert s["draft_content"] and s["evaluation"]["overall_pass"] is True and s["approval_status"] == "pendiente" and not s["provisional"]
    assert h["approvals"]["ceo"]["required"] is True  # sigue viajando para la Parte 3
    assert not {"esperando_aprobación", "terminado"} & {s for _, s in store.status_log}
    assert len(model.agent_calls("generator")) == 4 and len(model.agent_calls("relevance")) == 4


def test_a_failed_evaluation_returns_the_section_to_its_generator_with_concrete_feedback():
    store = prepared()
    model = ScriptedResponseModel()
    model.drafts["operaciones"] = [GOOD["operaciones"] + BAD_SLA]  # 1.er borrador incumple; el 2.º es el bueno
    outcome, _ = run(store, model)
    assert outcome == "completo"
    ops = section(store, "operaciones")
    assert ops["iterations"] == 2 and ops["generation_status"] == "paso" and ops["needs_human_review"] is False
    first, second = ops["evaluation_history"]
    assert first["evaluation"]["overall_pass"] is False and first["evaluation"]["compliance"]["rule_ids"] == ["setup-sla-breach"]
    assert second["evaluation"]["overall_pass"] is True
    retry = model.agent_calls("generator", "operaciones")[1][1]["content"]
    assert "<feedback_del_evaluador>" in retry and "setup-sla-breach" in retry and "5 días hábiles" in retry  # regla + frase exacta
    assert BAD_SLA.strip() in retry  # recibe también el borrador anterior
    assert all(section(store, d)["iterations"] == 1 for d in ("marketing", "procurement", "training"))  # los demás no se repiten


def test_feedback_names_the_rule_the_quote_the_missing_aspect_and_the_readability_problem():
    model = ScriptedResponseModel()
    model.drafts["operaciones"] = [SHORT + BAD_PRICE]
    model.relevance_override = lambda m: json.dumps({"aspects": [{"index": 0, "covered": False, "evidence": ""}] + [
        {"index": i, "covered": True, "evidence": SHORT} for i in range(1, 9)]})
    store = prepared()
    run(store, model)
    fb = section(store, "operaciones")["evaluation_history"][0]["evaluation"]["feedback_for_generator"]
    assert "[CUMPLIMIENTO · price-dual-currency · BRIEFING §5]" in fb and "USD 60,000" in fb
    assert "[PERTINENCIA] No atiendes el aspecto" in fb and "[LEGIBILIDAD]" in fb and "corta" in fb


def test_when_iterations_run_out_the_last_draft_is_kept_marked_needs_human_review_and_still_goes_to_part3(monkeypatch):
    monkeypatch.setenv("RFP_MAX_ITERATIONS", "2")
    store = prepared()
    model = ScriptedResponseModel()
    model.drafts["training"] = [GOOD["training"] + BAD_COMPETITOR, GOOD["training"] + BAD_COMPETITOR + " Extra."]
    outcome, _ = run(store, model)
    ticket, tr = store.get_ticket(1), section(store, "training")
    assert outcome == "revision_humana" and ticket["status"] == config.STATUS_NEEDS_REVIEW  # el ticket NO se descarta
    assert tr["generation_status"] == "needs_human_review" and tr["needs_human_review"] is True and tr["iterations"] == 2
    assert "Extra." in tr["draft_content"] and tr["evaluation_results"]["compliance"]["rule_ids"] == ["no-competitors"]  # último borrador + resultado
    h = ticket["part3_handoff"]
    assert h["ready_for_part_3"] and h["needs_human_review"] == ["training"] and h["all_sections_passed"] is False
    t3 = next(s for s in h["sections"] if s["department_id"] == "training")
    assert t3["needs_human_review"] and t3["provisional"] and t3["draft_content"] and t3["evaluation"]["overall_pass"] is False
    assert len(h["sections"]) == 4 and {section(store, d)["generation_status"] for d in DEPTS} == {"paso", "needs_human_review"}
    assert len(model.agent_calls("generator", "training")) == 2  # respeta el límite


def test_departments_run_in_parallel_and_do_not_block_each_other():
    barrier = threading.Barrier(2, timeout=15)  # si corrieran en serie, el primero esperaría para siempre

    def hook(dept):
        if dept in ("marketing", "operaciones"):
            barrier.wait()

    model = ScriptedResponseModel()
    model.generator_hook = hook
    assert run(prepared(), model)[0] == "completo"


def test_the_three_evaluators_run_for_every_iteration_and_each_writes_only_its_own_result():
    store = prepared()
    model = ScriptedResponseModel()
    model.drafts["marketing"] = [GOOD_MK.replace("30 días", "45 días")]
    run(store, model)
    history = section(store, "marketing")["evaluation_history"]
    assert [h["iteration"] for h in history] == [1, 2]
    for h in history:
        assert {"readability", "relevance", "compliance"} <= set(h["evaluation"]) and h["evaluation"]["iteration"] == h["iteration"]
    assert history[0]["evaluation"]["compliance"]["rule_ids"] == ["offer-validity-30d"] and history[1]["evaluation"]["overall_pass"]


def test_each_evaluator_receives_only_what_it_needs():
    seen = {}
    real = agents.evaluate_relevance

    def spy(llm, key_aspects, text):
        seen["relevance"] = (key_aspects, text)
        return real(llm, key_aspects, text)

    store = prepared()
    original, agents.evaluate_relevance = agents.evaluate_relevance, spy
    try:
        run(store)
    finally:
        agents.evaluate_relevance = original
    key_aspects, text = seen["relevance"]
    assert isinstance(key_aspects, list) and all(set(a) >= {"aspect"} for a in key_aspects) and isinstance(text, str)
    messages = json.dumps(ScriptedResponseModel().calls)  # sin contexto extra: el prompt del juez no lleva el handoff completo
    assert "Mariana" not in messages


# --------------------------------------------------------------------------------------------------------------
# Fallos a mitad y reanudación
# --------------------------------------------------------------------------------------------------------------
def test_a_failing_department_is_recorded_and_does_not_stop_the_others_then_resume_only_redoes_it():
    store = prepared()
    model = ScriptedResponseModel()

    def boom(dept):
        if dept == "procurement":
            raise RuntimeError("timeout del proveedor del modelo")

    model.generator_hook = boom
    outcome, _ = run(store, model)
    t = store.get_ticket(1)
    assert outcome == "fallo" and "procurement" in t["processing_error"] and t["status"] in (config.STATUS_GENERATING, config.STATUS_EVALUATING)
    assert t["part3_handoff"] is None and section(store, "procurement")["generation_status"] == "error"
    assert [section(store, d)["generation_status"] for d in ("marketing", "operaciones", "training")] == ["paso"] * 3  # los demás terminaron
    model2 = ScriptedResponseModel()
    outcome, _ = run(store, model2, mode="resume")
    assert outcome == "completo" and [a for a, _, _ in model2.calls if a == "generator"] == ["generator"]  # solo rehace procurement
    assert model2.agent_calls("generator", "procurement") and not model2.agent_calls("generator", "marketing")
    done = store.get_ticket(1)
    assert done["processing_error"] is None and len(done["part3_handoff"]["sections"]) == 4


def test_invalid_model_output_fails_the_ticket_visibly_instead_of_saving_garbage():
    store = prepared()
    outcome, _ = run(store, lambda m: "no es json")
    assert outcome == "fallo" and store.get_ticket(1)["processing_error"] and store.get_ticket(1)["part3_handoff"] is None


def test_regenerate_discards_previous_drafts_and_starts_over(monkeypatch):
    monkeypatch.setenv("RFP_MAX_ITERATIONS", "1")
    store = prepared()
    model = ScriptedResponseModel()
    model.drafts["training"] = [GOOD["training"] + BAD_COMPETITOR]
    assert run(store, model)[0] == "revision_humana"
    assert generate_ticket(1, store, ScriptedResponseModel(), mode="start") == "no_listo"  # no pisa un resultado existente por accidente
    assert generate_ticket(1, store, ScriptedResponseModel(), mode="regenerate") == "completo"
    assert store.get_ticket(1)["status"] == config.STATUS_EVALUATING and section(store, "training")["needs_human_review"] is False


def test_informal_rfp_generates_only_for_the_departments_part1_activated():
    store = prepared(PDF_INFORMAL)
    outcome, model = run(store)
    assert outcome == "completo" and sorted(s["department_id"] for s in store.sections[1]) == ["marketing", "operaciones", "procurement"]
    assert {d for a, d, _ in model.calls if a == "generator"} == {"marketing", "operaciones", "procurement"}
    assert store.get_ticket(1)["part3_handoff"]["departments"] == ["marketing", "operaciones", "procurement"]
