"""API de proveedores y contratos: identidad por directorio, aprobación humana, auditoría por agente y datos sensibles fuera de las respuestas."""
from __future__ import annotations

import json
from datetime import date

import pytest

from app.supplier_contracts import routes
from data.pipelines.supplier_contracts import config
from data.pipelines.supplier_contracts.engine import SupplierEngine
from data.pipelines.supplier_contracts.generate import SENSITIVE_VALUES
from data.pipelines.supplier_contracts.store import Store

FELIPE, MARIANA, LUCIA = "felipe.guerrero@brasaland-demo.com", "mariana.restrepo@brasaland-demo.com", "lucia.fernandez@brasaland-demo.com"
LOAD = date(2026, 11, 25)


@pytest.fixture
def engine(tmp_path):
    e = SupplierEngine(Store(tmp_path / "sc.db"))
    e.store.seed_staff()
    e.seed(LOAD, tmp_path / "data")
    routes.set_engine(e)
    yield e
    routes.set_engine(None)


@pytest.fixture
def as_(client, auth_headers):
    cache: dict[str, dict] = {}

    def _as(email: str):
        if email not in cache:
            cache[email] = auth_headers(email=email)
        return cache[email]
    return _as


ENDPOINTS = [("get", "/supplier-contracts/suppliers"), ("get", "/supplier-contracts/alerts"), ("post", "/supplier-contracts/ask"),
             ("get", "/supplier-contracts/suppliers/BR-S05/prices"), ("get", "/supplier-contracts/suppliers/BR-S05/contract"),
             ("get", "/supplier-contracts/communications"), ("get", "/supplier-contracts/audit/events")]


def call(client, method, url, headers=None, json=None):
    kw = {"json": json} if method == "post" else {}
    return getattr(client, method)(url, headers=headers, **kw)


def test_every_endpoint_requires_login(client, engine):
    for method, url in ENDPOINTS:
        assert call(client, method, url, json={"question": "hola"} if method == "post" else None).status_code == 401, url


def test_only_the_directory_can_read_even_a_platform_admin_cannot(client, engine, as_, make_headers):
    stranger = as_("alguien.mas@brasaland-demo.com")
    admin = make_headers("admin.plataforma@brasaland-demo.com", "admin")
    for headers in (stranger, admin):
        for method, url in ENDPOINTS:
            assert call(client, method, url, headers, json={"question": "hola"} if method == "post" else None).status_code == 403, url


def test_requests_before_loading_data_say_so(client, tmp_path, as_):
    routes.set_engine(SupplierEngine(Store(tmp_path / "empty.db")))
    try:
        response = client.post("/supplier-contracts/ask", json={"question": "¿Qué dice el contrato de Carnes del Valle?"}, headers=as_(FELIPE))
        assert response.status_code == 409 and "seed" in response.json()["detail"]
    finally:
        routes.set_engine(None)


def test_seed_is_for_operations_or_procurement_and_loads_everything(client, tmp_path, monkeypatch, as_):
    monkeypatch.setenv("SUPPLIER_CONTRACTS_DATA_DIR", str(tmp_path / "gen"))
    routes.set_engine(SupplierEngine(Store(tmp_path / "s.db")))
    try:
        assert client.post("/supplier-contracts/seed", headers=as_(MARIANA)).status_code == 403
        r = client.post("/supplier-contracts/seed", headers=as_(LUCIA))
        assert r.status_code == 200 and r.json()["price_rows"] == 96 and len(r.json()["contracts"]) == 4 and r.json()["alerts"] >= 6
        names = {s["id"]: s["has_contract"] for s in client.get("/supplier-contracts/suppliers", headers=as_(FELIPE)).json()}
        assert names == {"BR-S01": True, "BR-S02": True, "BR-S03": False, "BR-S04": False, "BR-S05": True, "BR-S06": False, "BR-S07": False, "BR-S08": True}
    finally:
        routes.set_engine(None)


def test_alerts_reach_procurement_and_operations(client, engine, as_):
    for who in (LUCIA, FELIPE):
        alerts = client.get("/supplier-contracts/alerts", headers=as_(who)).json()
        assert len(alerts) == 6 and {a["kind"] for a in alerts} == {"price_increase", "contract_expiry", "notice_deadline"}
        assert all(a["recipients"] == ["s-lucia", "s-felipe"] for a in alerts)
    assert client.post("/supplier-contracts/alerts/scan", headers=as_(MARIANA)).status_code == 403
    assert len(client.post("/supplier-contracts/alerts/scan", headers=as_(LUCIA)).json()) == 6


def test_ask_returns_the_traceable_answer(client, engine, as_):
    r = client.post("/supplier-contracts/ask", json={"question": "¿La subida de Sunshine Prime Meats está permitida por el contrato?"}, headers=as_(FELIPE))
    body = r.json()
    assert r.status_code == 200 and body["intent"] == "permitted" and body["consults_used"] == 2
    assert "NO, el contrato no la permite" in body["answer"] and body["citations"][0]["clause"] and body["citations"][0]["page"] >= 1
    q = client.post("/supplier-contracts/ask", json={"question": "¿Qué dice el contrato de Hortalizas La Sabana?"}, headers=as_(FELIPE)).json()
    assert "No hay contrato" in q["answer"]
    assert client.post("/supplier-contracts/ask", json={"question": "x"}, headers=as_(FELIPE)).status_code == 400


def test_contract_and_price_views_carry_their_sources(client, engine, as_):
    c = client.get("/supplier-contracts/suppliers/BR-S02/contract", headers=as_(LUCIA)).json()
    assert c["contract_id"] == "CT-BR-03" and not [t for t in c["terms"] if t["kind"] == "renewal_notice"]
    assert all(t["clause"] and t["page"] for t in c["terms"])
    p = client.get("/supplier-contracts/suppliers/BR-S02/prices", headers=as_(LUCIA)).json()
    assert len(p["history"]) == 12 and all(f["sources"][0]["file"] == "price_history.csv" for f in p["history"])
    assert client.get("/supplier-contracts/suppliers/BR-S03/contract", headers=as_(LUCIA)).json()["status"] == "no_contract"
    assert client.get("/supplier-contracts/suppliers/BR-S99/prices", headers=as_(LUCIA)).status_code == 404


def test_notices_change_the_verdict_and_are_restricted(client, engine, as_):
    ask = lambda: client.post("/supplier-contracts/ask", json={"question": "¿La subida de Sunshine Prime Meats está permitida por el contrato?"}, headers=as_(FELIPE)).json()["answer"]
    assert "NO, el contrato no la permite" in ask()
    assert client.post("/supplier-contracts/notices", json={"supplier_id": "BR-S05", "kind": "index_evidence", "ref": "11"}, headers=as_(MARIANA)).status_code == 403
    assert client.post("/supplier-contracts/notices", json={"supplier_id": "BR-S05", "kind": "index_evidence", "ref": "mucho"}, headers=as_(LUCIA)).status_code == 422
    for kind, ref in (("index_evidence", "11"), ("price_increase_notice", "carta-001")):
        assert client.post("/supplier-contracts/notices", json={"supplier_id": "BR-S05", "kind": kind, "ref": ref}, headers=as_(LUCIA)).status_code == 201
    assert "SÍ, el contrato la permite" in ask()


def test_brief_draft_needs_both_approvers_before_anything_is_sent(client, engine, as_):
    assert client.post("/supplier-contracts/brief", json={"supplier_id": "BR-S05", "draft_message": True}, headers=as_(MARIANA)).status_code == 403
    r = client.post("/supplier-contracts/brief", json={"supplier_id": "BR-S05", "draft_message": True}, headers=as_(LUCIA))
    assert r.status_code == 200 and "Brief de renegociación" in r.json()["answer"]
    cid = r.json()["brief"]["communication_id"]
    comm = client.get("/supplier-contracts/communications", headers=as_(FELIPE)).json()[0]
    assert comm["id"] == cid and comm["status"] == "pending_approval" and comm["required_roles"] == ["ops_director", "ceo"] and comm["created_by"] == "agent:supplier-supervisor"
    url = f"/supplier-contracts/communications/{cid}"
    assert client.post(f"{url}/decision", json={"decision": "approve"}, headers=as_(LUCIA)).status_code == 403          # Compras no aprueba
    assert client.post(f"{url}/send", headers=as_(FELIPE)).status_code == 409                                           # sin aprobar: no sale
    assert client.post(f"{url}/decision", json={"decision": "approve"}, headers=as_(FELIPE)).json()["missing_roles"] == ["ceo"]
    assert client.post(f"{url}/send", headers=as_(FELIPE)).status_code == 409                                           # falta Mariana
    assert client.post(f"{url}/decision", json={"decision": "approve"}, headers=as_(FELIPE)).status_code == 409         # ya aprobó
    assert client.post(f"{url}/decision", json={"decision": "approve"}, headers=as_(MARIANA)).json()["status"] == "approved"
    assert client.post(f"{url}/send", headers=as_(MARIANA)).status_code == 403                                          # solo Felipe da la orden
    assert client.post(f"{url}/send", headers=as_(FELIPE)).json()["status"] == "sent"
    assert client.post(f"{url}/decision", json={"decision": "approve"}, headers=as_(FELIPE)).status_code == 409
    assert client.post("/supplier-contracts/communications/999/send", headers=as_(FELIPE)).status_code == 404


def test_audit_shows_which_agent_did_what_and_only_to_felipe_and_mariana(client, engine, as_):
    client.post("/supplier-contracts/ask", json={"question": "¿La subida de Sunshine Prime Meats está permitida por el contrato?"}, headers=as_(FELIPE))
    assert client.get("/supplier-contracts/audit/events", headers=as_(LUCIA)).status_code == 403
    events = client.get("/supplier-contracts/audit/events", headers=as_(MARIANA)).json()
    actors = {e["actor_id"] for e in events if e["actor_type"] == "agent"}
    assert actors == {"agent:supplier-supervisor", "agent:price-specialist", "agent:contract-specialist"}
    messages = client.get("/supplier-contracts/audit/messages", headers=as_(FELIPE)).json()
    assert {m["sender"] for m in messages} >= {"agent:supplier-supervisor", "agent:price-specialist", "agent:contract-specialist"}


def test_no_endpoint_ever_returns_sensitive_contract_data(client, engine, as_):
    blobs = []
    for sid in ("BR-S01", "BR-S02", "BR-S05", "BR-S08"):
        blobs.append(client.get(f"/supplier-contracts/suppliers/{sid}/contract", headers=as_(FELIPE)).text)
        blobs.append(client.get(f"/supplier-contracts/suppliers/{sid}/prices", headers=as_(FELIPE)).text)
        blobs.append(client.post("/supplier-contracts/brief", json={"supplier_id": sid, "draft_message": True}, headers=as_(FELIPE)).text)
    for q in ("¿Qué dice el contrato de Carnes del Valle?", "¿Qué dice el contrato de Sunshine Prime Meats?", "¿Cuál es el preaviso de Brava Beverages?"):
        blobs.append(client.post("/supplier-contracts/ask", json={"question": q}, headers=as_(FELIPE)).text)
    for url in ("alerts", "communications", "audit/events", "audit/messages"):
        blobs.append(client.get(f"/supplier-contracts/{url}", headers=as_(FELIPE)).text)
    blob = "\n".join(blobs)
    assert "price_history" in blob and "cláusula" in blob.lower()
    for secret in SENSITIVE_VALUES:
        assert secret not in blob, secret
