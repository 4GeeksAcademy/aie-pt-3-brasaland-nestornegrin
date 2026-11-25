"""Orquestador de onboarding: grafo explícito, reanudación tras reinicio, comprobación obligatoria, aprobaciones humanas, plazos y datos sensibles."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from data.pipelines.onboarding import (Forbidden, NotAwaiting, NotCorporate, OnboardingEngine, OnboardingError, OnboardingStore,
                                      build_checkpointer, config, knowledge, quiz, schedule, thread_id)
from data.pipelines.onboarding.graph import PermissionDenied
from data.pipelines.onboarding.sensitive import contains_sensitive, redact
from data.pipelines.onboarding.seed import DOCS_OK, STAFF, seed

NOW = datetime(2026, 11, 25, 15, 0, tzinfo=timezone.utc)
SECRETS = ("1037456789", "1.037.456.789", "4532015112830366", "123-45-6789", "7.500.000", "$4,200")


def make(tmp_path, clock=None):
    return OnboardingEngine(OnboardingStore(tmp_path / "o.db"), build_checkpointer(tmp_path / "cp.db"), clock or (lambda: NOW))


@pytest.fixture
def engine(tmp_path):
    e = make(tmp_path)
    for row in STAFF:
        e.store.upsert_staff(*row)
    return e


def register(engine, name="Ana Ruiz", email="ana@brasaland-demo.com", position="Analista de Brasaland Digital", department="Brasaland Digital",
             site="Medellín", manager="s-santiago", start=date(2026, 11, 23)):
    record = engine.register("s-camilo", dict(name=name, email=email, position=position, department=department, site=site, manager_id=manager,
                                              start_date=start))
    engine.start(record["id"])
    return record["id"]


def staff(engine, key):
    return engine.store.staff(key)


def solve(engine, oid, correct=True):
    pending = engine.awaiting(oid)
    stage = config.STAGE_BY_NUMBER[pending["stage"]]
    variant = engine.store.onboarding(oid)["variant"]
    answers = {q: (quiz.question_by_id(stage, variant, q).answer + (0 if correct else 1)) % 4 for q in pending["question_ids"]}
    engine.check_answers(oid, answers)
    engine.apply_answers(oid, answers)


def approve(engine, oid, who, **flags):
    engine.check_decision(oid, staff(engine, who), "approve", None, flags)
    engine.apply_decision(oid, who, "approve", None, flags)


def walk_to(engine, oid, stage_number):
    """Conduce la incorporación hasta que el agente espere en `stage_number`."""
    steps = {1: lambda: approve(engine, oid, "s-camilo", **DOCS_OK), 2: lambda: solve(engine, oid), 3: lambda: solve(engine, oid),
             4: lambda: approve(engine, oid, "s-felipe"), 5: lambda: None, 6: lambda: solve(engine, oid), 7: lambda: solve(engine, oid)}
    while engine.store.onboarding(oid)["current_stage"] < stage_number:
        current = engine.store.onboarding(oid)["current_stage"]
        if current == 5:
            solve(engine, oid)
            approve(engine, oid, "s-santiago")
        else:
            steps[current]()


# -------------------------------------------------------------------------------------------------------------- grafo y material
def test_stage_graph_matches_the_briefing_exactly():
    assert [(s.number, s.deadline_day, s.approver) for s in config.STAGES] == [
        (1, 2, "people_team"), (2, 3, None), (3, 5, None), (4, 7, "ops_supervisor"), (5, 8, "direct_manager"), (6, 9, None), (7, 9, None),
        (8, 10, "people_manager")]
    assert [s.quiz for s in config.STAGES] == [False, True, True, False, True, True, True, False]
    assert config.PASS_THRESHOLD == 0.8 and config.FAILED_ATTEMPTS_BEFORE_NOTIFY == 2 and config.REMINDER_HOURS_BEFORE == 24
    assert config.TOTAL_DELAY_DAYS_FOR_PEOPLE_MANAGER == 3 and 4 <= config.QUESTIONS_PER_ATTEMPT <= 6


def test_official_material_and_quizzes_are_consistent():
    docs = knowledge.load_documents()
    assert len(docs) == 7 and sum(1 for k in docs if k.startswith("etapa-5")) >= 2
    for stage in config.STAGES:
        if not stage.quiz:
            continue
        for variant in (config.VARIANTS if stage.number == 5 else [None]):
            bank = quiz.load_bank(quiz.bank_key(stage, variant))
            assert len(bank) >= config.QUESTIONS_PER_ATTEMPT * 1.5  # hay preguntas distintas para el segundo intento
            for question in bank:
                assert knowledge.find_section(question.source), question.id


def test_quiz_questions_never_expose_the_answer(engine):
    oid = register(engine)
    walk_to(engine, oid, 2)
    view = engine.person_view(oid)
    assert view["quiz"] and "answer" not in json.dumps(view["quiz"]["questions"])
    assert 4 <= len(view["quiz"]["questions"]) <= 6


def test_content_is_adapted_to_site_and_position(engine):
    miami = register(engine, "Dan Foster", "dan@brasaland-demo.com", "Coordinador de Marketing", "Marketing", "Miami", "s-emily")
    med = register(engine)
    for oid in (miami, med):
        approve(engine, oid, "s-camilo", **DOCS_OK)
    titles = lambda oid: " ".join(s["title"] for s in engine.person_view(oid)["presentation"]["sections"])  # noqa: E731
    assert "Miami" in titles(miami) and "Miami" not in titles(med)


# --------------------------------------------------------------------------------------------------- restricción corporativa
@pytest.mark.parametrize("department,position", [("Cocina", "Cocinero"), ("Sala", "Mesero"), ("Operaciones", "Jefe de cocina de local"),
                                                  ("Operaciones", "Mesera de sala")])
def test_restaurant_positions_are_rejected_with_the_exact_message(engine, department, position):
    with pytest.raises(NotCorporate) as error:
        register(engine, position=position, department=department)
    assert error.value.message == ("Este flujo es para incorporaciones al equipo corporativo. "
                                   "Las incorporaciones de restaurante se mantienen con su responsable de local.".replace("mantienen", "gestionan"))
    assert engine.store.onboardings() == []


def test_unknown_function_variant_is_not_invented(engine):
    with pytest.raises(OnboardingError, match="material oficial"):
        register(engine, position="Analista de Formación", department="Formación")


# ------------------------------------------------------------------------------------------------------- reanudación tras reinicio
def test_restart_resumes_exactly_at_the_same_stage(tmp_path):
    first = make(tmp_path)
    for row in STAFF:
        first.store.upsert_staff(*row)
    oid = register(first)
    walk_to(first, oid, 3)
    solve(first, oid, correct=False)  # intento fallido en la etapa 3
    before = (first.awaiting(oid), first.store.quiz(oid), first.store.onboarding(oid)["current_stage"])
    del first  # «el servicio se cae»

    second = make(tmp_path)  # proceso nuevo: nuevo grafo, nuevo checkpointer, mismos ficheros
    assert (second.awaiting(oid), second.store.quiz(oid), second.store.onboarding(oid)["current_stage"]) == before
    assert before[0]["kind"] == "quiz" and before[0]["stage"] == 3 and before[0]["attempt"] == 1
    solve(second, oid)
    assert second.awaiting(oid)["stage"] == 4  # y sigue desde ahí, sin repetir ni saltar etapas
    assert [s["status"] for s in second.store.stages(oid)][:3] == ["completed"] * 3


def test_restart_while_waiting_for_a_human_keeps_the_pending_approval(tmp_path):
    first = make(tmp_path)
    for row in STAFF:
        first.store.upsert_staff(*row)
    oid = register(first)
    walk_to(first, oid, 4)
    del first
    second = make(tmp_path)
    assert second.awaiting(oid) == {"kind": "approval", "stage": 4, "approver": "ops_supervisor", "approver_label": "Supervisor de Operaciones"}
    approve(second, oid, "s-felipe")
    assert second.store.onboarding(oid)["current_stage"] == 5


# ----------------------------------------------------------------------------------------------------------------- paralelismo
def test_parallel_onboardings_have_isolated_state(engine):
    a, b = register(engine), register(engine, "Bea Gil", "bea@brasaland-demo.com", "Coordinadora de Marketing", "Marketing", "Miami", "s-emily")
    assert thread_id(a) != thread_id(b)
    walk_to(engine, a, 4)
    assert engine.store.onboarding(b)["current_stage"] == 1 and engine.awaiting(b)["stage"] == 1
    assert engine.store.quiz(b) is None
    assert {e["onboarding_id"] for e in engine.store.events(b)} == {b}


# ------------------------------------------------------------------------------------------- comprobación obligatoria y refuerzo
def test_no_content_stage_passes_without_its_comprehension_check(engine):
    oid = register(engine)
    approve(engine, oid, "s-camilo", **DOCS_OK)
    with pytest.raises(OnboardingError):
        engine.check_answers(oid, {})                       # sin respuestas
    with pytest.raises(NotAwaiting):
        engine.check_decision(oid, staff(engine, "s-camilo"), "approve", None, {})  # no hay aprobación que saltarse
    solve(engine, oid, correct=False)
    assert engine.store.onboarding(oid)["current_stage"] == 2
    view = engine.person_view(oid)
    assert view["quiz"]["attempt"] == 2 and view["quiz"]["reinforce"]  # vuelve a presentar los puntos fallados
    first_ids = engine.store.quiz(oid)["question_ids"]
    assert len(set(first_ids)) == len(first_ids)


def test_second_attempt_uses_different_questions_and_two_failures_notify_the_manager(engine):
    oid = register(engine)
    approve(engine, oid, "s-camilo", **DOCS_OK)
    first = set(engine.awaiting(oid)["question_ids"])
    solve(engine, oid, correct=False)
    second = set(engine.awaiting(oid)["question_ids"])
    assert second != first
    assert not [n for n in engine.store.notifications("staff", "s-santiago") if n["kind"] == "quiz_failed_twice"]
    solve(engine, oid, correct=False)
    assert [n for n in engine.store.notifications("staff", "s-santiago") if n["kind"] == "quiz_failed_twice"]
    solve(engine, oid)  # y aun así puede superarla después
    assert engine.store.onboarding(oid)["current_stage"] == 3


def test_threshold_is_80_percent(engine):
    oid = register(engine)
    approve(engine, oid, "s-camilo", **DOCS_OK)
    pending = engine.awaiting(oid)
    stage, variant = config.STAGE_BY_NUMBER[2], engine.store.onboarding(oid)["variant"]
    answers = {q: quiz.question_by_id(stage, variant, q).answer for q in pending["question_ids"]}
    wrong_one = pending["question_ids"][0]
    answers[wrong_one] = (answers[wrong_one] + 1) % 4          # 4 de 5 = 80 % → supera
    engine.apply_answers(oid, answers)
    assert engine.store.onboarding(oid)["current_stage"] == 3


def test_shadow_day_cannot_start_before_passing_stage_3(engine):
    oid = register(engine)
    walk_to(engine, oid, 3)
    with pytest.raises(NotAwaiting):
        engine.check_decision(oid, staff(engine, "s-felipe"), "approve", None, {})
    assert engine.store.stage(oid, 4)["status"] == "pending"
    solve(engine, oid)
    assert engine.store.stage(oid, 4)["status"] == "active"


# --------------------------------------------------------------------------------------------------------------- aprobaciones
def test_approval_requires_the_right_role_and_department(engine):
    oid = register(engine)
    wrong = [staff(engine, k) for k in ("s-santiago", "s-emily", "s-felipe", None)]
    for person in wrong:
        with pytest.raises(Forbidden):
            engine.check_decision(oid, person, "approve", None, DOCS_OK)
    engine.store.upsert_staff("s-fake", "Falso Personas", "fake@brasaland-demo.com", "Compras", config.ROLE_PEOPLE_TEAM, "Miami")
    with pytest.raises(Forbidden):  # rol de Personas pero en OTRO departamento
        engine.check_decision(oid, staff(engine, "s-fake"), "approve", None, DOCS_OK)
    assert engine.store.onboarding(oid)["current_stage"] == 1 and engine.awaiting(oid)["kind"] == "approval"
    with pytest.raises(OnboardingError, match="recibidos"):
        engine.check_decision(oid, staff(engine, "s-camilo"), "approve", None, {})
    approve(engine, oid, "s-camilo", **DOCS_OK)


def test_function_stage_needs_check_and_direct_manager_only(engine):
    oid = register(engine)
    walk_to(engine, oid, 5)
    assert engine.awaiting(oid)["kind"] == "quiz"  # primero la comprobación…
    solve(engine, oid)
    assert engine.awaiting(oid)["approver"] == "direct_manager"  # …y después el responsable directo
    for who in ("s-emily", "s-ashley", "s-camilo", "s-felipe"):  # ni otro responsable ni Ashley ni Personas
        with pytest.raises(Forbidden):
            engine.check_decision(oid, staff(engine, who), "approve", None, {})
    approve(engine, oid, "s-santiago")
    assert engine.store.onboarding(oid)["current_stage"] == 6


def test_rejecting_the_function_stage_restarts_it_with_a_visible_comment(engine):
    oid = register(engine)
    walk_to(engine, oid, 5)
    solve(engine, oid)
    with pytest.raises(OnboardingError, match="comentario"):
        engine.check_decision(oid, staff(engine, "s-santiago"), "reject", " ", {})
    engine.check_decision(oid, staff(engine, "s-santiago"), "reject", "Revisa tus objetivos de 90 días", {})
    engine.apply_decision(oid, "s-santiago", "reject", "Revisa tus objetivos de 90 días", {})
    view = engine.person_view(oid)
    assert view["current_stage"] == 5 and view["last_rejection_comment"] == "Revisa tus objetivos de 90 días"
    assert engine.awaiting(oid)["kind"] == "quiz" and engine.store.stage(oid, 5)["rejections"] == 1
    assert [n for n in engine.store.notifications("person", oid) if n["kind"] == "stage_rejected"]
    solve(engine, oid)
    approve(engine, oid, "s-santiago")
    assert engine.store.onboarding(oid)["current_stage"] == 6


def test_full_onboarding_closes_only_with_ashley_and_confirmed_accesses(engine):
    oid = register(engine)
    walk_to(engine, oid, 8)
    for who in ("s-camilo", "s-santiago"):
        with pytest.raises(Forbidden):
            engine.check_decision(oid, staff(engine, who), "approve", None, {"accesses_confirmed": True})
    with pytest.raises(OnboardingError):
        engine.check_decision(oid, staff(engine, "s-ashley"), "approve", None, {})
    approve(engine, oid, "s-ashley", accesses_confirmed=True)
    record = engine.store.onboarding(oid)
    assert record["status"] == "completed" and all(s["status"] == "completed" for s in engine.store.stages(oid))


# ------------------------------------------------------------------------------------------------------------ plazos y escalado
def test_business_day_deadlines_follow_the_briefing():
    start = date(2026, 11, 23)  # lunes
    assert schedule.nth_business_day(start, 10) == date(2026, 12, 4)
    assert schedule.nth_business_day(date(2026, 11, 21), 1) == date(2026, 11, 23)  # empieza en sábado → lunes
    assert schedule.deadline_at(start, 2, "Medellín") == datetime(2026, 11, 24, 23, 0, tzinfo=timezone.utc)  # 18:00 hora de Colombia


def test_reminder_24h_before_then_manager_escalation_then_ashley(tmp_path):
    clock = {"now": datetime(2026, 11, 23, 14, 0, tzinfo=timezone.utc)}
    engine = make(tmp_path, lambda: clock["now"])
    for row in STAFF:
        engine.store.upsert_staff(*row)
    oid = register(engine)
    deadline = datetime.fromisoformat(engine.store.stage(oid, 1)["deadline_at"])
    assert engine.sweep(deadline - timedelta(hours=30)) == []
    kinds = lambda s: [x["kind"] for x in s]  # noqa: E731
    assert kinds(engine.sweep(deadline - timedelta(hours=23))) == ["reminder"]
    assert [n for n in engine.store.notifications("person", oid) if n["kind"] == "reminder"]
    assert engine.sweep(deadline - timedelta(hours=2)) == []                      # el recordatorio se envía una vez
    sent = engine.sweep(deadline + timedelta(hours=1))
    assert kinds(sent) == ["stage_overdue"] and sent[0]["to"] == "staff:s-santiago"  # responsable directo
    assert engine.sweep(deadline + timedelta(days=2)) == []                         # 2 días hábiles: aún no hay aviso a Ashley
    late = engine.sweep(deadline + timedelta(days=8))
    assert kinds(late) == ["delay_over_3_days"] and late[0]["to"] == "staff:s-ashley"


def test_seeded_blocked_onboarding_is_escalated(tmp_path):
    engine = make(tmp_path)
    seed(engine)
    rows = {r["name"]: r for r in engine.board()}
    mateo = rows["Mateo Restrepo"]
    assert mateo["blocked"] and mateo["current_stage"] == 4 and mateo["waiting_on"] == "Supervisor de Operaciones"
    assert not rows["Laura Gómez"]["blocked"] and not rows["Daniel Foster"]["blocked"]
    assert {r["site"] for r in rows.values()} == {"Medellín", "Miami"}
    sent = {(s["kind"], s["to"]) for s in engine.sweep()}
    assert ("stage_overdue", "staff:s-santiago") in sent and ("delay_over_3_days", "staff:s-ashley") in sent
    assert len({s["manager_id"] for s in rows.values()}) >= 2
    assert seed(engine) == {r["email"]: r["id"] for r in engine.store.onboardings()}  # idempotente


# ----------------------------------------------------------------------------------------------------------------- dudas
def test_official_answers_cite_sources_and_out_of_scope_is_derived(engine):
    oid = register(engine)
    ok = engine.ask(oid, "¿Cuándo se hace el pedido semanal a proveedores?")
    assert ok["answered"] and ok["sources"][0]["ref"].startswith("etapa-3-como-opera-un-restaurante#")
    out = engine.ask(oid, "¿Cuántos días de vacaciones me corresponden?")
    assert not out["answered"] and out["sources"] == [] and out["derived_to"].startswith("Personas")
    assert "no voy a inventar" in out["answer"]
    assert [n for n in engine.store.notifications("staff", "s-ashley") if n["kind"] == "question_derived"]
    assert [q["answered"] for q in engine.store.questions(oid)] == [1, 0] or [q["answered"] for q in engine.store.questions(oid)] == [True, False]


# ------------------------------------------------------------------------------------------------------- identidad del agente
def test_agent_has_its_own_narrow_identity(engine):
    assert config.AGENT_ACTOR.startswith("agent:") and config.AGENT_ACTOR not in {s[0] for s in STAFF}
    assert {"approve_stage", "confirm_shadow_day", "read_sensitive_documents", "send_email", "delete_onboarding", "modify_approvers"} & set(
        config.AGENT_PERMISSIONS) == set()
    assert set(config.AGENT_FORBIDDEN) >= {"approve_stage", "read_sensitive_data"}
    with pytest.raises(PermissionDenied):
        engine.agent.act("approve_stage", None, "approved_by_agent")
    with pytest.raises(PermissionDenied):
        engine.agent.require("read_sensitive_data")


def test_every_agent_action_is_logged_as_automated_process(engine):
    oid = register(engine)
    walk_to(engine, oid, 4)
    events = engine.store.events(oid)
    agent = [e for e in events if e["actor_id"] == config.AGENT_ACTOR]
    assert agent and {e["actor_type"] for e in agent} == {"automated_process"}
    human = [e for e in events if e["actor_type"] != "automated_process"]
    assert human and all(e["actor_id"] != config.AGENT_ACTOR for e in human)
    assert {"stage_entered", "stage_completed"} <= {e["action"] for e in agent}


# ----------------------------------------------------------------------------------------------------------- datos sensibles
def test_redaction_covers_id_numbers_bank_data_and_salary():
    for text in ("mi cédula es 1.037.456.789", "SSN 123-45-6789", "cuenta 4532015112830366", "mi salario es 7.500.000 COP", "I earn $4,200 a month",
                 "pasaporte AB1234567"):
        clean, kinds = redact(text)
        assert kinds and contains_sensitive(text) and not any(s in clean for s in SECRETS), text
    assert redact("¿Cuántos locales tiene Brasaland en Florida?") == ("¿Cuántos locales tiene Brasaland en Florida?", [])


def test_sensitive_data_never_reaches_logs_store_checkpoint_or_notifications(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    engine = make(tmp_path)
    for row in STAFF:
        engine.store.upsert_staff(*row)
    oid = register(engine)
    approve(engine, oid, "s-camilo", **DOCS_OK)
    engine.ask(oid, "Mi cédula es 1.037.456.789 y mi cuenta 4532015112830366, ¿la necesitáis?")
    engine.ask(oid, "Mi salario es de 7.500.000 pesos, ¿cuándo me pagan?")
    engine.apply_decision(oid, "s-santiago", "reject", "comentario con SSN 123-45-6789", {})  # no hay aprobación abierta: se ignora
    assert engine.awaiting(oid)["kind"] == "quiz"
    walk_to(engine, oid, 5)
    solve(engine, oid)
    engine.check_decision(oid, staff(engine, "s-santiago"), "reject", "Cobra $4,200 y su cédula 1037456789 no coincide", {})
    engine.apply_decision(oid, "s-santiago", "reject", "Cobra $4,200 y su cédula 1037456789 no coincide", {})
    engine.sweep(NOW + timedelta(days=30))
    engine.store._conn.commit() if hasattr(engine.store, "_conn") else None

    blobs = [caplog.text, json.dumps(engine.board(), ensure_ascii=False), json.dumps(engine.person_view(oid), ensure_ascii=False)]
    for path in (tmp_path / "o.db", tmp_path / "cp.db"):
        con = sqlite3.connect(path)
        for (table,) in con.execute("select name from sqlite_master where type='table'"):
            for row in con.execute(f"select * from {table}"):
                blobs.append(repr([c.decode("latin1") if isinstance(c, bytes) else c for c in row]))
        con.close()
    haystack = "\n".join(blobs)
    for secret in SECRETS:
        assert secret not in haystack, secret
    assert any(e["detail"] for e in engine.store.events(oid))


def test_paperwork_stores_only_status_flags(engine):
    oid = register(engine)
    approve(engine, oid, "s-camilo", **DOCS_OK)
    assert set(engine.store.paperwork(oid)) <= {"onboarding_id", "contract_received", "payroll_docs_received", "shadow_day_confirmed", "accesses_confirmed"}
    with pytest.raises(Exception):
        engine.store.set_paperwork(oid, document_number="1037456789")
