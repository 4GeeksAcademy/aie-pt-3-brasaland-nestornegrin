"""API del orquestador de onboarding: identidad, permisos de aprobación, restricción corporativa, dudas y datos sensibles.
TestClient ejecuta las BackgroundTasks al terminar la petición, así que tras un POST el agente ya avanzó."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.onboarding import routes
from data.pipelines.onboarding import OnboardingEngine, OnboardingStore, build_checkpointer, config, quiz
from data.pipelines.onboarding.seed import seed

NOW = datetime(2026, 11, 25, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def engine(tmp_path):
    engine = OnboardingEngine(OnboardingStore(tmp_path / "o.db"), build_checkpointer(tmp_path / "cp.db"), lambda: NOW)
    seed(engine)
    routes.set_engine(engine)
    yield engine
    routes.set_engine(None)


@pytest.fixture
def as_(client, auth_headers):
    cache: dict[str, dict] = {}  # registrar e iniciar sesión (bcrypt) una sola vez por correo y test

    def _as(email: str):
        if email not in cache:
            cache[email] = auth_headers(email=email)
        return cache[email]
    return _as


def ids(engine):
    return {r["name"].split()[0].lower(): r["id"] for r in engine.store.onboardings()}


def correct_answers(engine, oid):
    pending = engine.awaiting(oid)
    record = engine.store.onboarding(oid)
    stage = config.STAGE_BY_NUMBER[pending["stage"]]
    return {q: quiz.question_by_id(stage, record["variant"], q).answer for q in pending["question_ids"]}


def test_requires_login(client, engine):
    assert client.get("/onboarding").status_code == 401


def test_restaurant_position_is_rejected_with_the_exact_message(client, engine, as_):
    body = {"name": "Carlos Pérez", "email": "carlos@brasaland-demo.com", "position": "Cocinero", "department": "Cocina", "site": "Medellín",
            "manager_id": "s-santiago", "start_date": "2026-12-01"}
    response = client.post("/onboarding", json=body, headers=as_("camilo.duarte@brasaland-demo.com"))
    assert response.status_code == 422
    assert response.json()["detail"] == ("Este flujo es para incorporaciones al equipo corporativo. "
                                         "Las incorporaciones de restaurante se gestionan con su responsable de local.")
    body["department"], body["position"] = "Operaciones", "Mesero de sala"
    assert client.post("/onboarding", json=body, headers=as_("camilo.duarte@brasaland-demo.com")).status_code == 422


def test_only_people_team_registers_and_the_agent_starts_in_background(client, engine, as_):
    body = {"name": "Sara León", "email": "sara.leon@brasaland-demo.com", "position": "Analista de Compras", "department": "Compras",
            "site": "Miami", "manager_id": "s-lucia", "start_date": "2026-12-01"}
    assert client.post("/onboarding", json=body, headers=as_("emily.carter@brasaland-demo.com")).status_code == 403
    response = client.post("/onboarding", json=body, headers=as_("camilo.duarte@brasaland-demo.com"))
    assert response.status_code == 202
    oid = response.json()["id"]
    assert engine.awaiting(oid)["kind"] == "approval" and engine.awaiting(oid)["stage"] == 1


def test_board_is_for_people_and_managers_only_see_their_team(client, engine, as_):
    assert len(client.get("/onboarding", headers=as_("ashley.turner@brasaland-demo.com")).json()) == 3
    mine = client.get("/onboarding", headers=as_("emily.carter@brasaland-demo.com")).json()
    assert [r["name"] for r in mine] == ["Daniel Foster"]
    assert client.get("/onboarding", headers=as_("laura.gomez@brasaland-demo.com")).status_code == 403
    blocked = [r for r in client.get("/onboarding", headers=as_("ashley.turner@brasaland-demo.com")).json() if r["blocked"]]
    assert [r["name"] for r in blocked] == ["Mateo Restrepo"] and blocked[0]["current_stage"] == 4


def test_person_sees_own_progress_and_cannot_open_others(client, engine, as_):
    headers = as_("laura.gomez@brasaland-demo.com")
    me = client.get("/onboarding/me", headers=headers).json()
    assert me["current_stage"] == 2 and me["quiz"] and me["presentation"]["sections"]
    assert "answer" not in json.dumps(me["quiz"]["questions"]) and "Retira" not in me["quiz"]["questions"][0].get("answer", "")
    assert me["remaining"][0] == "La empresa"
    assert client.get(f"/onboarding/{ids(engine)['mateo']}", headers=headers).status_code == 404


def test_comprehension_gate_over_the_api(client, engine, as_):
    headers = as_("laura.gomez@brasaland-demo.com")
    oid = ids(engine)["laura"]
    qs = engine.awaiting(oid)["question_ids"]
    assert client.post(f"/onboarding/{oid}/answers", json={"answers": {qs[0]: 0}}, headers=headers).status_code == 422
    wrong = {q: (correct_answers(engine, oid)[q] + 1) % 4 for q in qs}
    assert client.post(f"/onboarding/{oid}/answers", json={"answers": wrong}, headers=headers).status_code == 202
    assert engine.store.onboarding(oid)["current_stage"] == 2  # no pasa
    assert client.post(f"/onboarding/{oid}/answers", json={"answers": correct_answers(engine, oid)}, headers=headers).status_code == 202
    assert engine.store.onboarding(oid)["current_stage"] == 3
    other = as_("mateo.restrepo@brasaland-demo.com")
    assert client.post(f"/onboarding/{oid}/answers", json={"answers": {}}, headers=other).status_code == 403


def test_only_the_right_person_can_confirm_the_shadow_day(client, engine, as_):
    oid = ids(engine)["mateo"]
    url = f"/onboarding/{oid}/decision"
    for email in ("camilo.duarte@brasaland-demo.com", "santiago.ruiz@brasaland-demo.com", "ashley.turner@brasaland-demo.com", "mateo.restrepo@brasaland-demo.com"):
        assert client.post(url, json={"decision": "approve"}, headers=as_(email)).status_code == 403, email
    assert engine.store.onboarding(oid)["current_stage"] == 4
    assert client.post(url, json={"decision": "approve"}, headers=as_("felipe.guerrero@brasaland-demo.com")).status_code == 202
    assert engine.store.onboarding(oid)["current_stage"] == 5


def test_function_stage_needs_the_direct_manager_and_rejection_restarts_it(client, engine, as_):
    oid = ids(engine)["mateo"]
    client.post(f"/onboarding/{oid}/decision", json={"decision": "approve"}, headers=as_("felipe.guerrero@brasaland-demo.com"))
    client.post(f"/onboarding/{oid}/answers", json={"answers": correct_answers(engine, oid)}, headers=as_("mateo.restrepo@brasaland-demo.com"))
    assert engine.awaiting(oid) == {"kind": "approval", "stage": 5, "approver": "direct_manager", "approver_label": "Responsable directo"}
    url = f"/onboarding/{oid}/decision"
    assert client.post(url, json={"decision": "approve"}, headers=as_("emily.carter@brasaland-demo.com")).status_code == 403  # otro departamento
    assert client.post(url, json={"decision": "reject"}, headers=as_("santiago.ruiz@brasaland-demo.com")).status_code == 422  # sin comentario
    assert client.post(url, json={"decision": "reject", "comment": "Repasa los objetivos de los 90 días"},
                       headers=as_("santiago.ruiz@brasaland-demo.com")).status_code == 202
    view = client.get("/onboarding/me", headers=as_("mateo.restrepo@brasaland-demo.com")).json()
    assert view["current_stage"] == 5 and view["last_rejection_comment"] == "Repasa los objetivos de los 90 días"
    assert engine.awaiting(oid)["kind"] == "quiz"  # vuelve al inicio de la etapa


def test_close_needs_ashley_and_active_accesses(client, engine, as_):
    oid = ids(engine)["mateo"]
    mateo = as_("mateo.restrepo@brasaland-demo.com")
    client.post(f"/onboarding/{oid}/decision", json={"decision": "approve"}, headers=as_("felipe.guerrero@brasaland-demo.com"))
    client.post(f"/onboarding/{oid}/answers", json={"answers": correct_answers(engine, oid)}, headers=mateo)
    client.post(f"/onboarding/{oid}/decision", json={"decision": "approve"}, headers=as_("santiago.ruiz@brasaland-demo.com"))
    for _ in (6, 7):
        client.post(f"/onboarding/{oid}/answers", json={"answers": correct_answers(engine, oid)}, headers=mateo)
    assert engine.awaiting(oid)["stage"] == 8
    url = f"/onboarding/{oid}/decision"
    assert client.post(url, json={"decision": "approve", "accesses_confirmed": True}, headers=as_("camilo.duarte@brasaland-demo.com")).status_code == 403
    assert client.post(url, json={"decision": "approve"}, headers=as_("ashley.turner@brasaland-demo.com")).status_code == 422
    assert client.post(url, json={"decision": "approve", "accesses_confirmed": True}, headers=as_("ashley.turner@brasaland-demo.com")).status_code == 202
    assert engine.store.onboarding(oid)["status"] == "completed"
    assert client.get("/onboarding/me", headers=mateo).json()["progress"] == {"completed": 8, "total": 8}


def test_official_answer_cites_source_and_out_of_scope_is_derived(client, engine, as_):
    oid = ids(engine)["laura"]
    headers = as_("laura.gomez@brasaland-demo.com")
    ok = client.post(f"/onboarding/{oid}/questions", json={"question": "¿Cuántos restaurantes tiene Brasaland?"}, headers=headers).json()
    assert ok["answered"] and ok["sources"] and ok["derived_to"] is None
    out = client.post(f"/onboarding/{oid}/questions", json={"question": "¿Cuántos días de vacaciones tengo?"}, headers=headers).json()
    assert not out["answered"] and out["sources"] == [] and "Personas" in out["derived_to"]
    inbox = client.get("/onboarding/notifications", headers=as_("ashley.turner@brasaland-demo.com")).json()
    assert any(n["kind"] == "question_derived" for n in inbox)
    assert client.post(f"/onboarding/{oid}/questions", json={"question": "hola?"}, headers=as_("mateo.restrepo@brasaland-demo.com")).status_code == 403


def test_sweep_escalates_overdue_stage_to_manager_and_ashley(client, engine, as_):
    assert client.post("/onboarding/sweep", headers=as_("laura.gomez@brasaland-demo.com")).status_code == 403
    sent = client.post("/onboarding/sweep", headers=as_("camilo.duarte@brasaland-demo.com")).json()["sent"]
    assert {(s["kind"], s["to"]) for s in sent} >= {("stage_overdue", "staff:s-santiago"), ("delay_over_3_days", "staff:s-ashley")}
    assert client.post("/onboarding/sweep", headers=as_("camilo.duarte@brasaland-demo.com")).json()["sent"] == []  # una sola vez
    assert any(n["kind"] == "stage_overdue" for n in client.get("/onboarding/notifications", headers=as_("santiago.ruiz@brasaland-demo.com")).json())


def test_events_are_logged_as_automated_process(client, engine, as_):
    oid = ids(engine)["mateo"]
    events = client.get(f"/onboarding/{oid}/events", headers=as_("ashley.turner@brasaland-demo.com")).json()
    agent_events = [e for e in events if e["actor_id"] == config.AGENT_ACTOR]
    assert agent_events and {e["actor_type"] for e in agent_events} == {"automated_process"}
    assert client.get(f"/onboarding/{oid}/events", headers=as_("santiago.ruiz@brasaland-demo.com")).status_code == 403


def test_api_responses_never_carry_sensitive_data(client, engine, as_):
    oid = ids(engine)["laura"]
    headers = as_("laura.gomez@brasaland-demo.com")
    client.post(f"/onboarding/{oid}/questions", json={"question": "Mi cédula es 1.037.456.789 y mi cuenta 4532015112830366, ¿qué hago?"}, headers=headers)
    client.post(f"/onboarding/{oid}/questions", json={"question": "Mi salario es de 4.500 dólares al mes"}, headers=headers)
    texts = [client.get(u, headers=as_("ashley.turner@brasaland-demo.com")).text for u in ("/onboarding", f"/onboarding/{oid}", f"/onboarding/{oid}/events")]
    texts.append(client.get("/onboarding/notifications", headers=as_("ashley.turner@brasaland-demo.com")).text)
    for text in texts:
        for secret in ("1.037.456.789", "1037456789", "4532015112830366", "4.500"):
            assert secret not in text
