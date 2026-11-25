"""API del cierre financiero: identidad por directorio, revisión solo por Felipe, visibilidad, trazabilidad y datos sensibles fuera de las respuestas."""
from __future__ import annotations

import json
from datetime import date

import pytest

from app.financial_close import routes
from data.pipelines.financial_close import config, generate
from data.pipelines.financial_close.store import CloseStore, DataStore
from data.pipelines.financial_close.workflow import CloseEngine

FELIPE, MARIANA, NICOLAS = "felipe.guerrero@brasaland-demo.com", "mariana.restrepo@brasaland-demo.com", "nicolas.park@brasaland-demo.com"
PERIOD = "2026-10"


@pytest.fixture
def engine(tmp_path):
    src = tmp_path / "csv"
    generate.generate(src, date(2026, 11, 25))
    e = CloseEngine(DataStore(tmp_path / "d.db"), CloseStore(tmp_path / "c.db"))
    e.load_period(src, PERIOD)
    e.run_close(PERIOD)
    routes.set_engine(e)
    yield e
    routes.set_engine(None)


@pytest.fixture
def as_(client, auth_headers):
    cache: dict = {}

    def _as(email):
        if email not in cache:
            cache[email] = auth_headers(email=email)
        return cache[email]
    return _as


def rid(engine):
    return engine.latest(PERIOD)["id"]


def test_endpoints_require_login(client, engine):
    for method, url in (("get", "/financial-close/reports"), ("get", f"/financial-close/reports/{rid(engine)}"), ("post", f"/financial-close/reports/{rid(engine)}/review"),
                        ("get", "/financial-close/audit/events"), ("post", "/financial-close/demo")):
        assert getattr(client, method)(url).status_code == 401, url


def test_directory_only_even_platform_admin_is_refused(client, engine, as_, make_headers):
    for headers in (as_("alguien.mas@brasaland-demo.com"), make_headers("admin.plataforma@brasaland-demo.com", "admin")):
        assert client.get("/financial-close/reports", headers=headers).status_code == 403
        assert client.post(f"/financial-close/reports/{rid(engine)}/review", json={"decision": "approve"}, headers=headers).status_code == 403


def test_pending_report_is_visible_only_to_the_reviewer(client, engine, as_):
    i = rid(engine)
    assert [r["id"] for r in client.get("/financial-close/reports", headers=as_(FELIPE)).json()] == [i]
    assert client.get("/financial-close/reports", headers=as_(MARIANA)).json() == []
    assert client.get(f"/financial-close/reports/{i}", headers=as_(MARIANA)).status_code == 403
    body = client.get(f"/financial-close/reports/{i}", headers=as_(FELIPE)).json()
    assert body["status"] == "pending_review" and "## 6. Anexo de trazabilidad" in body["markdown"]


def test_only_felipe_can_approve_and_then_everyone_sees_it(client, engine, as_):
    i = rid(engine)
    assert client.post(f"/financial-close/reports/{i}/review", json={"decision": "approve"}, headers=as_(MARIANA)).status_code == 403
    assert client.post(f"/financial-close/reports/{i}/review", json={"decision": "approve"}, headers=as_(NICOLAS)).status_code == 403
    assert engine.get(i)["status"] == "pending_review"
    ok = client.post(f"/financial-close/reports/{i}/review", json={"decision": "approve"}, headers=as_(FELIPE))
    assert ok.status_code == 200 and ok.json()["status"] == "distributed"
    assert client.get(f"/financial-close/reports/{i}", headers=as_(MARIANA)).status_code == 200
    assert client.post(f"/financial-close/reports/{i}/review", json={"decision": "approve"}, headers=as_(FELIPE)).status_code == 409


def test_rejection_needs_comments_and_returns_the_new_version(client, engine, as_):
    i = rid(engine)
    assert client.post(f"/financial-close/reports/{i}/review", json={"decision": "reject"}, headers=as_(FELIPE)).status_code == 400
    assert client.post(f"/financial-close/reports/{i}/review", json={"decision": "otra"}, headers=as_(FELIPE)).status_code == 400
    r = client.post(f"/financial-close/reports/{i}/review", json={"decision": "reject", "comment": "Detalla Marketing de Florida"}, headers=as_(FELIPE))
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["status"] == "pending_review" and r.json()["content"]["revision"][0]["handled"]
    assert engine.get(i)["status"] == "rejected"
    assert [x["version"] for x in client.get("/financial-close/reports", headers=as_(FELIPE)).json()] == [2, 1]


def test_figure_origin_can_be_consulted(client, engine, as_):
    i = rid(engine)
    f = client.get(f"/financial-close/reports/{i}/figures/FL.MKT.ACT", headers=as_(FELIPE))
    assert f.status_code == 200 and len(f.json()["records"]) == 3 and f.json()["records"][0]["entry_id"].startswith("L-FL-")
    assert client.get(f"/financial-close/reports/{i}/figures/NO.EXISTE", headers=as_(FELIPE)).status_code == 404
    assert client.get(f"/financial-close/reports/{i}/figures/FL.MKT.ACT", headers=as_(MARIANA)).status_code == 403


def test_audit_endpoints_show_the_agent_as_automated_process(client, engine, as_, make_headers):
    client.post(f"/financial-close/reports/{rid(engine)}/review", json={"decision": "approve"}, headers=as_(FELIPE))
    ev = client.get("/financial-close/audit/events", headers=as_(MARIANA)).json()
    assert {e["actor_type"] for e in ev if e["actor_id"] == config.AGENT_ID} == {"automated_process"}
    assert any(e["actor_type"] == "user" and e["actor_id"] == "s-felipe" for e in ev)
    assert client.get("/financial-close/audit/events", headers=as_("lucia.fernandez@brasaland-demo.com")).status_code == 403
    msgs = client.get("/financial-close/audit/messages", headers=as_(FELIPE)).json()
    assert len([m for m in msgs if m["kind"] == "distribution"]) == 7


def test_demo_and_tick_are_operator_only(client, engine, as_, tmp_path, monkeypatch):
    monkeypatch.setenv("FINANCIAL_CLOSE_FILES_DIR", str(tmp_path / "files"))
    assert client.post("/financial-close/demo", headers=as_(MARIANA)).status_code == 403
    assert client.post("/financial-close/schedule/tick", headers=as_(MARIANA)).status_code == 403
    assert client.post("/financial-close/schedule/tick", headers=as_(FELIPE)).status_code == 200


def test_sensitive_values_never_appear_in_any_response(client, engine, as_):
    i = rid(engine)
    client.post(f"/financial-close/reports/{i}/review", json={"decision": "reject", "comment": f"Revisa la cuenta {generate.SENSITIVE_VALUES[0]} en Marketing"}, headers=as_(FELIPE))
    i2 = rid(engine)
    client.post(f"/financial-close/reports/{i2}/review", json={"decision": "approve"}, headers=as_(FELIPE))
    urls = ["/financial-close/reports", f"/financial-close/reports/{i}", f"/financial-close/reports/{i2}", "/financial-close/audit/events", "/financial-close/audit/messages",
            f"/financial-close/reports/{i2}/figures/FL.BEEF.ACT"]
    blob = json.dumps([client.get(u, headers=as_(FELIPE)).json() for u in urls], ensure_ascii=False)
    for v in generate.SENSITIVE_VALUES:
        assert v not in blob, v
