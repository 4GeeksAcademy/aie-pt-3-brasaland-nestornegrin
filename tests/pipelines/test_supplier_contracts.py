"""Proveedores y contratos: supervisor + especialistas. Escenarios A–D del briefing, trazabilidad, cálculos deterministas, alertas,
aprobaciones, identidad de agentes y datos sensibles."""
from __future__ import annotations

import csv
import logging
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pdfplumber
import pytest

from data.pipelines.supplier_contracts import config, tools
from data.pipelines.supplier_contracts.agents import PermissionDenied, Toolbox
from data.pipelines.supplier_contracts.approvals import Approvals, ApprovalError
from data.pipelines.supplier_contracts.engine import SupplierEngine
from data.pipelines.supplier_contracts.generate import SENSITIVE_VALUES, generate, price_rows
from data.pipelines.supplier_contracts.ingest import extract_terms
from data.pipelines.supplier_contracts.pdfgen import PAGE_BREAK, build_pdf
from data.pipelines.supplier_contracts.schemas import ContractRequest, PriceRequest
from data.pipelines.supplier_contracts.sensitive import contains_sensitive, redact
from data.pipelines.supplier_contracts.store import Store

LOAD = date(2026, 11, 25)
D = Decimal


@pytest.fixture
def engine(tmp_path):
    e = SupplierEngine(Store(tmp_path / "sc.db"))
    e.seed(LOAD, tmp_path / "data")
    e.data_dir = tmp_path / "data"
    return e


def staff(engine, role):
    return next(engine.store.staff(s[0]) for s in config.STAFF if s[3] == role)


# ============================================================ cálculos deterministas
def test_variation_impact_and_conversion_are_exact():
    assert tools.pct_change(D("7.20"), D("8.064")) == D("12.00")
    assert tools.pct_change(D("38000"), D("39520")) == D("4.00")
    assert tools.monthly_impact(D("11500"), D("12535"), 4250) == D("4398750.00")       # (12.535 − 11.500) × 4.250 kg
    assert tools.monthly_impact(D("7.20"), D("8.064"), 2400) == D("2073.60")
    assert tools.convert(D("4000"), "COP", "USD") == D("1.00") and tools.convert(D("2"), "USD", "COP") == D("8000.00")
    assert tools.to_usd(D("1276800000"), "COP") == D("319200.00")
    assert tools.cpi_cap(D("1")) == D("6.20")


def test_thresholds_are_the_briefings_and_strict():
    assert tools.threshold_for(config.BEEF) == 3 and tools.threshold_for("Pollo") == 8
    assert tools.exceeds_threshold(D("3.01"), config.BEEF) and not tools.exceeds_threshold(D("3.00"), config.BEEF)
    assert tools.exceeds_threshold(D("9"), "Pollo") and not tools.exceeds_threshold(D("6"), "Bebidas")
    with pytest.raises(ValueError):
        tools.pct_change(D("0"), D("1"))


def test_alert_stages_follow_the_briefing():
    assert [tools.expiry_stage(n) for n in (120, 91, 90, 75, 31, 30, 20, -3)] == [None, None, 90, 90, 90, 30, 30, 30]
    assert tools.notice_due(15) and tools.notice_due(5) and tools.notice_due(-2) and not tools.notice_due(16)
    assert tools.notice_deadline(date(2027, 2, 8), 45) == date(2026, 12, 25)


def test_peer_gap_and_cross_market_units():
    diff, pct, saving = tools.peer_gap(D("8.064"), D("7.05"), 2400)
    assert (diff, pct, saving) == (D("-1.01"), D("-12.57"), D("2433.60"))
    assert tools.price_per_kg_usd(D("38000"), "kg", "COP") == D("9.50")
    assert tools.price_per_kg_usd(D("7.20"), "lb", "USD") == D("15.87")
    with pytest.raises(ValueError):
        tools.price_per_kg_usd(D("1"), "caja", "USD")


# ============================================================ datos de prueba (briefing)
def test_price_history_has_12_months_small_steps_and_the_four_scenarios():
    rows = price_rows(LOAD)
    assert len(rows) == 8 * 12
    by = {}
    for r in rows:
        by.setdefault(r["supplier_id"], []).append(r)
    for sid, series in by.items():
        months = [r["month"] for r in series]
        assert months == sorted(months) and months[-1] == "2026-11" and months[0] == "2025-12"
        prices = [D(r["unit_price"]) for r in series]
        for a, b in zip(prices[:11], prices[1:11]):                     # los 11 primeros meses: ±1 % como máximo
            assert abs(b / a - 1) <= D("0.0101")
    last = {sid: (D(s[-2]["unit_price"]), D(s[-1]["unit_price"])) for sid, s in by.items()}
    assert tools.pct_change(*last["BR-S05"]) == 12 and tools.pct_change(*last["BR-S01"]) == 4
    assert tools.pct_change(*last["BR-S02"]) == 9 and tools.pct_change(*last["BR-S08"]) == 6
    for sid in ("BR-S03", "BR-S04", "BR-S06", "BR-S07"):
        assert abs(tools.pct_change(*last[sid])) <= 1
    assert {sid: s[-1]["monthly_volume"] for sid, s in by.items()}["BR-S04"] == 0


def test_generated_contracts_are_numbered_clauses_with_sensitive_billing(tmp_path):
    out = generate(tmp_path, LOAD)
    assert [p.name for p in out["contracts"]] == ["CT-BR-01.pdf", "CT-BR-02.pdf", "CT-BR-03.pdf", "CT-BR-04.pdf"]
    for pdf_path in out["contracts"]:
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join(p.extract_text() for p in pdf.pages)
        assert len(pdf.pages) == 3 and text.count("Cláusula ") + text.count("Clause ") == 8
        assert any(v in text for v in SENSITIVE_VALUES), "el contrato de prueba debe llevar datos sensibles en facturación"
    assert "Cláusula 3. No renovación" in pdfplumber.open(tmp_path / "CT-BR-01.pdf").pages[1].extract_text()
    rows = list(csv.DictReader((tmp_path / "price_history.csv").open()))
    assert list(rows[0]) == ["supplier_id", "product", "unit", "currency", "month", "unit_price", "monthly_volume"]


def test_contract_dates_are_relative_to_the_load_date(tmp_path):
    other = date(2027, 3, 1)
    e = SupplierEngine(Store(tmp_path / "x.db"))
    e.seed(other, tmp_path / "d")
    expiries = {c["contract_id"]: d for c in e.store.q("SELECT contract_id, params FROM terms WHERE kind='expiry'") for d in [__import__("json").loads(c["params"])["date"]]}
    assert expiries == {spec.id: (other + timedelta(days=spec.expires_in_days)).isoformat() for spec in config.CONTRACTS}


# ============================================================ ingesta: trazabilidad
def test_every_price_keeps_its_csv_file_and_row(engine):
    lines = (engine.data_dir / "price_history.csv").read_text().splitlines()
    for row in engine.store.q("SELECT * FROM prices"):
        cells = lines[row["source_row"] - 1].split(",")
        assert row["source_file"] == "price_history.csv"
        assert (cells[0], cells[4], cells[5]) == (row["supplier_id"], row["month"], row["unit_price"])


def test_every_term_has_clause_page_quote_in_the_contract_language(engine):
    terms = engine.store.q("SELECT t.*, c.file FROM terms t JOIN contracts c ON c.id=t.contract_id")
    assert terms and all(t["clause"] and t["page"] >= 1 and t["quote"] for t in terms)
    es = [t for t in terms if t["contract_id"] in ("CT-BR-01", "CT-BR-03")]
    en = [t for t in terms if t["contract_id"] in ("CT-BR-02", "CT-BR-04")]
    assert all(t["language"] == "es" for t in es) and all(t["language"] == "en" for t in en)
    t = engine.store.one("SELECT * FROM terms WHERE contract_id='CT-BR-02' AND kind='price_review'")
    assert (t["clause"], t["page"]) == ("4", 2) and "reference beef index" in t["quote"]


def test_ct_br_03_has_no_notice_clause_and_billing_is_dropped(engine):
    kinds = {r["kind"] for r in engine.store.q("SELECT kind FROM terms WHERE contract_id='CT-BR-03'")}
    assert "renewal_notice" not in kinds and "billing" not in kinds
    assert not engine.store.q("SELECT 1 FROM terms WHERE quote LIKE '%Cuenta%' OR quote LIKE '%Bank account%'")


def test_low_confidence_extraction_is_marked_doubtful_and_never_used_as_firm(tmp_path):
    lines = ["CONTRATO DE SUMINISTRO CT-BR-09", "", "Cláusula 1. Objeto. Suministro de carne.", "Cláusula 2. Vencimiento. El contrato vence cuando las partes lo decidan.",
             PAGE_BREAK, "Cláusula 3. Revisión de precios. Los precios podrán ajustarse de común acuerdo.",
             "Cláusula 4. Terminación anticipada. Se podrá terminar el contrato."]
    pdf = tmp_path / "CT-BR-09.pdf"
    pdf.write_bytes(build_pdf(lines))
    terms, pages = extract_terms(pdf, "es", "CT-BR-09")
    assert pages == 2 and {t["kind"] for t in terms} == {"expiry", "price_review", "exit"}
    assert all(t["doubtful"] and t["confidence"] < 0.7 for t in terms)
    assert next(t for t in terms if t["kind"] == "price_review")["page"] == 2


def test_doubtful_clause_gives_an_indeterminate_verdict_not_a_guess(engine):
    engine.store.run("UPDATE terms SET doubtful=1, confidence=0.4 WHERE contract_id='CT-BR-01' AND kind='price_review'")
    r = engine.supervisor.contract.handle(ContractRequest(action="evaluate_increase", supplier_id="BR-S01", as_of=LOAD, increase_pct=D("4")), "t")
    assert r.verdict.verdict == "indeterminate" and any("baja confianza" in m for m in r.missing)


# ============================================================ escenarios A–D
def evaluate(engine, supplier_id):
    price = engine.supervisor.price.handle(PriceRequest(action="detect_increase", supplier_id=supplier_id, as_of=LOAD), "t")
    contract = engine.supervisor.contract.handle(ContractRequest(action="evaluate_increase", supplier_id=supplier_id, as_of=LOAD, increase_pct=price.increase.pct), "t")
    return price.increase, contract


def test_scenario_a_sunshine_12pct_exceeds_and_is_not_permitted(engine):
    inc, c = evaluate(engine, "BR-S05")
    assert inc.pct == 12 and inc.exceeds and c.verdict.verdict == "not_permitted"
    text = " ".join(c.verdict.reasons)
    assert "FIJO" in text and "No hay registro de la prueba del índice" in text and "No hay registro del preaviso escrito" in text
    assert any(x.clause == "4" and x.page == 2 and x.language == "en" for x in c.citations)


def test_scenario_a_changes_only_with_both_notice_and_index_evidence(engine):
    engine.store.add_notice("BR-S05", "price_increase_notice", "carta-001")
    assert evaluate(engine, "BR-S05")[1].verdict.verdict == "not_permitted"
    engine.store.add_notice("BR-S05", "index_evidence", "8.5")                      # el índice subió 8,5 % < 10 %
    assert evaluate(engine, "BR-S05")[1].verdict.verdict == "not_permitted"
    engine.store.add_notice("BR-S05", "index_evidence", "11.0")
    assert evaluate(engine, "BR-S05")[1].verdict.verdict == "permitted"


def test_scenario_b_carnes_del_valle_4pct_is_permitted_below_cpi_plus_one(engine):
    inc, c = evaluate(engine, "BR-S01")
    assert inc.pct == 4 and inc.exceeds
    assert c.verdict.verdict == "permitted" and c.verdict.allowed_max_pct == D("6.20")
    assert any("preaviso escrito" in p for p in c.verdict.pending_conditions)        # lo que no se puede verificar se declara


def test_scenario_c_avicola_9pct_exceeds_the_annual_cap(engine):
    inc, c = evaluate(engine, "BR-S02")
    assert inc.pct == 9 and inc.exceeds and c.verdict.verdict == "not_permitted" and c.verdict.allowed_max_pct == 5
    assert "excede el máximo anual del 5%" in c.verdict.reasons[0]


def test_scenario_d_brava_6pct_is_below_threshold_and_has_no_price_alert(engine):
    inc, c = evaluate(engine, "BR-S08")
    assert inc.pct == 6 and not inc.exceeds and c.verdict.verdict == "permitted"
    assert not [a for a in engine.alerts.listing() if a["kind"] == "price_increase" and a["supplier_id"] == "BR-S08"]
    assert [a for a in engine.alerts.listing() if a["kind"] == "contract_expiry" and a["supplier_id"] == "BR-S08"]


# ============================================================ alertas
def test_alerts_at_load_date_match_the_briefing(engine):
    alerts = engine.alerts.listing()
    kinds = sorted((a["kind"], a["supplier_id"]) for a in alerts)
    assert kinds == [("contract_expiry", "BR-S05"), ("contract_expiry", "BR-S08"), ("notice_deadline", "BR-S08"),
                     ("price_increase", "BR-S01"), ("price_increase", "BR-S02"), ("price_increase", "BR-S05")]
    by = {(a["kind"], a["supplier_id"]): a for a in alerts}
    assert by[("contract_expiry", "BR-S05")]["stage"] == 90 and by[("contract_expiry", "BR-S08")]["stage"] == 30
    assert by[("notice_deadline", "BR-S08")]["detail"]["days_left"] == 5
    assert all(a["recipients"] == ["s-lucia", "s-felipe"] for a in alerts)
    pa = by[("price_increase", "BR-S05")]
    assert pa["detail"]["verdict"]["verdict"] == "not_permitted" and pa["detail"]["citations"] and "NO permitida" in pa["message"]


def test_alerts_follow_time_and_are_idempotent(engine):
    before = len(engine.alerts.listing())
    assert len(engine.alerts.scan(LOAD)) == before                                   # misma fecha: nada se duplica
    later = {(a["kind"], a["supplier_id"], a["stage"]) for a in engine.alerts.scan(LOAD + timedelta(days=50))}
    assert ("contract_expiry", "BR-S01", 90) in later                                # CT-BR-01: 120 − 50 = 70 días
    assert ("notice_deadline", "BR-S01", 15) in later                                # preaviso 60 d → faltan 10
    assert ("contract_expiry", "BR-S05", 30) in later                                # 75 − 50 = 25 → etapa de 30 días
    assert not [a for a in later if a[1] == "BR-S03"]                                # sin contrato no hay alertas de contrato


def test_a_contract_without_notice_clause_never_gets_a_notice_alert(engine):
    later = engine.alerts.scan(LOAD + timedelta(days=190))
    assert not [a for a in later if a["kind"] == "notice_deadline" and a["supplier_id"] == "BR-S02"]
    assert [a for a in later if a["kind"] == "contract_expiry" and a["supplier_id"] == "BR-S02"]


# ============================================================ preguntas del briefing
def test_q1_sunshine_increase_is_not_allowed_with_clause_and_page(engine):
    r = engine.ask("¿La subida de Sunshine Prime Meats está permitida por el contrato?")
    assert r.intent == "permitted" and r.consulted == [config.PRICE_AGENT_ID, config.CONTRACT_AGENT_ID] and r.consults_used == 2
    assert "NO, el contrato no la permite" in r.answer and "cláusula 4, p. 2" in r.answer and "reference beef index" in r.answer


def test_q2_monthly_cost_of_avicola_is_computed_by_code(engine):
    r = engine.ask("¿Cuánto nos cuesta al mes la subida de Avícola Antioquia?")
    assert r.intent == "cost" and r.consulted == [config.PRICE_AGENT_ID]
    assert "4.398.750,00 COP al mes" in r.answer and "12.535" in r.answer and "price_history.csv fila" in r.answer
    assert any(f.key == "monthly_impact" and f.sources for f in r.facts)


def test_q3_alternative_to_carnes_del_valle_is_andino_and_is_a_quote(engine):
    r = engine.ask("¿Qué alternativa tenemos a Carnes del Valle y a qué precio?")
    assert "Frigorífico Andino" in r.answer and "COTIZACIÓN" in r.answer and "COP/kg" in r.answer
    assert "Gulf" not in r.answer                                                    # otro país: no se compara


def test_q4_when_to_warn_sunshine_not_to_renew(engine):
    r = engine.ask("¿Cuándo tenemos que avisar a Sunshine Prime Meats si no queremos renovar?")
    assert str(LOAD + timedelta(days=75 - 45)) in r.answer and "cláusula 3, p. 2" in r.answer and "AUTOMÁTICAMENTE" in r.answer


def test_q5_avicola_notice_is_not_specified(engine):
    r = engine.ask("¿Cuál es el preaviso de Avícola Antioquia?")
    assert "no especifica el preaviso" in r.answer and "no voy a suponer" in r.answer
    assert any("no especifica preaviso" in m for m in r.missing)


def test_q6_hortalizas_has_no_contract(engine):
    r = engine.ask("¿Qué dice el contrato de Hortalizas La Sabana?")
    assert "No hay contrato con Hortalizas La Sabana" in r.answer and not r.citations


def test_q7_brief_combines_both_specialists_with_traceability(engine):
    r = engine.ask("Prepárame un brief para renegociar con Sunshine Prime Meats.")
    assert r.intent == "brief" and r.consulted == [config.PRICE_AGENT_ID, config.CONTRACT_AGENT_ID]
    brief = r.brief["markdown"]
    for part in ("Histórico de 12 meses", "Impacto económico", "Comparación con otros proveedores", "Qué dice el contrato", "Recomendación", "Aprobación necesaria", "Trazabilidad"):
        assert part in brief
    assert r.brief["verdict"] == "no permitida" and r.brief["required_approvers"] == [config.ROLE_OPS_DIRECTOR, config.ROLE_CEO]
    assert "2.073,60 USD al mes" in brief and "cláusula 4, p. 2" in brief and "price_history.csv fila 37" in brief
    assert "34.560,00 USD" in brief and "Gulf Coast Beef Co." in brief and r.brief["traceability"]


def test_unknown_questions_do_not_consult_anyone(engine):
    r = engine.ask("¿Qué tiempo hará mañana?")
    assert r.consults_used == 0 and r.consulted == [] and r.missing


# ============================================================ declarar lo que falta
def test_no_peer_in_the_same_country_is_declared_not_invented(engine):
    r = engine.ask("¿Qué alternativa tenemos a Avícola Antioquia?")
    assert "No tengo alternativa comparable" in r.answer and "No hay otro proveedor de Pollo en Colombia" in r.answer


def test_quote_only_supplier_has_no_impact_figure(engine):
    p = engine.supervisor.price.handle(PriceRequest(action="detect_increase", supplier_id="BR-S04", as_of=LOAD), "t")
    assert p.increase.monthly_impact is None and any("solo cotización" in m for m in p.missing)


def test_cross_market_comparison_is_flagged_as_indicative(engine):
    r = engine.ask("Compara Carnes del Valle con Sunshine Prime Meats")
    assert r.intent == "alternative"
    p = engine.supervisor.price.handle(PriceRequest(action="peers", supplier_id="BR-S01", as_of=LOAD, compare_with="BR-S05"), "t")
    cross = next(x for x in p.peers if x.indicative)
    assert "SOLO ORIENTATIVA" in cross.note and "Mercados distintos" in cross.note and cross.unit == "kg" and cross.currency == "USD"
    assert "orientativa" in p.notes[-1]


def test_unknown_supplier_and_other_category_are_declared(engine):
    assert engine.supervisor.price.handle(PriceRequest(action="history", supplier_id="BR-S99", as_of=LOAD), "t").status == "not_found"
    p = engine.supervisor.price.handle(PriceRequest(action="peers", supplier_id="BR-S01", as_of=LOAD, compare_with="BR-S07"), "t")
    assert any("otra categoría" in m for m in p.missing) and not any(x.indicative for x in p.peers)


# ============================================================ supervisor: límite de consultas
def test_consult_limit_truncates_instead_of_looping(tmp_path):
    e = SupplierEngine(Store(tmp_path / "l.db"), consult_limit=1)
    e.seed(LOAD, tmp_path / "d")
    r = e.ask("¿La subida de Sunshine Prime Meats está permitida por el contrato?")
    assert r.truncated and r.consults_used == 1 and "Respuesta incompleta" in r.answer and "límite de 1 consultas" in " ".join(r.missing)
    b = e.brief("BR-S05")
    assert b.truncated and "incompleto" in b.brief["markdown"]


def test_no_request_ever_uses_more_than_the_limit(engine):
    for q in ("Prepárame un brief para renegociar con Sunshine Prime Meats.", "¿La subida de Carnes del Valle está permitida por el contrato?"):
        assert engine.ask(q).consults_used <= config.MAX_CONSULTS_PER_REQUEST == 4


# ============================================================ identidad y herramientas por agente
def test_each_agent_only_has_its_own_tools():
    perms = config.AGENT_PERMISSIONS
    assert perms[config.PRICE_AGENT_ID].isdisjoint(perms[config.SUPERVISOR_ID])
    assert "check_price_increase" not in perms[config.PRICE_AGENT_ID] and "read_prices" not in perms[config.CONTRACT_AGENT_ID]
    for forbidden in config.FORBIDDEN_FOR_AGENTS:
        assert all(forbidden not in p for p in perms.values())


def test_a_specialist_cannot_use_another_specialists_tool_and_it_is_logged(engine):
    box = Toolbox(engine.store, config.PRICE_AGENT_ID, "r1")
    with pytest.raises(PermissionDenied):
        box.use("check_price_increase", "BR-S05", lambda: "x")
    with pytest.raises(PermissionDenied):
        box.use("send_to_supplier", "BR-S05", lambda: "x")
    with pytest.raises(PermissionDenied):
        Toolbox(engine.store, "agent:intruso", "r1")
    denied = [e for e in engine.store.events() if e["action"] == "denied"]
    assert {e["detail"]["tool"] for e in denied} == {"check_price_increase", "send_to_supplier"} and all(e["actor_id"] == config.PRICE_AGENT_ID for e in denied)


def test_every_agent_action_is_logged_with_the_agent_that_did_it(engine):
    engine.ask("¿La subida de Sunshine Prime Meats está permitida por el contrato?")
    rows = [e for e in engine.store.events(500) if e["actor_type"] == "agent"]
    pairs = {(e["actor_id"], e["action"]) for e in rows}
    assert (config.SUPERVISOR_ID, "request_received") in pairs and (config.SUPERVISOR_ID, "tool:consult_price_specialist") in pairs
    assert (config.PRICE_AGENT_ID, "tool:read_prices") in pairs and (config.PRICE_AGENT_ID, "tool:detect_increase") in pairs
    assert (config.CONTRACT_AGENT_ID, "tool:check_price_increase") in pairs and (config.CONTRACT_AGENT_ID, "tool:compute_deadlines") in pairs
    assert not [e for e in rows if e["actor_id"] == config.PRICE_AGENT_ID and e["action"] == "tool:check_price_increase"]


def test_agents_talk_only_through_the_supervisor(engine):
    engine.ask("Prepárame un brief para renegociar con Sunshine Prime Meats.")
    msgs = engine.store.messages()
    brief = [m for m in msgs if m["sender"] == config.SUPERVISOR_ID][-2:]
    assert {m["recipient"] for m in brief} == {config.PRICE_AGENT_ID, config.CONTRACT_AGENT_ID}
    assert not [m for m in msgs if {m["sender"], m["recipient"]} == {config.PRICE_AGENT_ID, config.CONTRACT_AGENT_ID}]


# ============================================================ aprobación humana
def test_who_must_approve_follows_the_contract_value(engine):
    roles = {sid: engine.approvals.required_roles(sid) for sid in ("BR-S01", "BR-S05", "BR-S02", "BR-S08", "BR-S03")}
    both, ops = [config.ROLE_OPS_DIRECTOR, config.ROLE_CEO], [config.ROLE_OPS_DIRECTOR]
    assert roles["BR-S01"][0] == both and roles["BR-S01"][1] == D("319200.00")         # COP 1.276.800.000 = USD 319.200
    assert roles["BR-S05"][0] == both                                                  # USD 207.360 > 200.000
    assert roles["BR-S02"][0] == ops and roles["BR-S02"][1] == D("146625.00")          # COP 586.500.000
    assert roles["BR-S08"][0] == ops and roles["BR-S03"] == (ops, None)                # sin contrato: solo Felipe


def test_a_draft_is_born_pending_and_nothing_goes_out_without_all_approvals(engine):
    r = engine.brief("BR-S05", draft_message=True)
    cid = r.brief["communication_id"]
    comm = engine.approvals.get(cid)
    assert comm["status"] == "pending_approval" and comm["created_by"] == config.SUPERVISOR_ID and comm["missing_roles"] == [config.ROLE_OPS_DIRECTOR, config.ROLE_CEO]
    felipe, mariana, lucia = (staff(engine, x) for x in (config.ROLE_OPS_DIRECTOR, config.ROLE_CEO, config.ROLE_PROCUREMENT))
    with pytest.raises(ApprovalError):                                                 # no se puede enviar sin aprobar
        engine.approvals.send(cid, felipe)
    with pytest.raises(ApprovalError) as e:                                            # Lucía no es aprobadora
        engine.approvals.decide(cid, lucia, "approve")
    assert e.value.status_code == 403
    assert engine.approvals.decide(cid, felipe, "approve")["status"] == "pending_approval"   # falta Mariana
    with pytest.raises(ApprovalError):
        engine.approvals.send(cid, felipe)
    with pytest.raises(ApprovalError) as dup:
        engine.approvals.decide(cid, felipe, "approve")
    assert dup.value.status_code == 409
    assert engine.approvals.decide(cid, mariana, "approve")["status"] == "approved"
    with pytest.raises(ApprovalError):                                                 # solo Felipe da la orden de envío
        engine.approvals.send(cid, mariana)
    assert engine.approvals.send(cid, felipe)["status"] == "sent"


def test_small_contract_needs_only_felipe_and_marianas_approval_is_not_valid_alone(engine):
    cid = engine.brief("BR-S02", draft_message=True).brief["communication_id"]
    felipe, mariana = staff(engine, config.ROLE_OPS_DIRECTOR), staff(engine, config.ROLE_CEO)
    with pytest.raises(ApprovalError):
        engine.approvals.decide(cid, mariana, "approve")                               # Mariana no es aprobadora de este
    assert engine.approvals.decide(cid, felipe, "approve")["status"] == "approved"


def test_rejection_is_final_and_agents_and_strangers_cannot_approve(engine):
    cid = engine.brief("BR-S01", draft_message=True).brief["communication_id"]
    felipe = staff(engine, config.ROLE_OPS_DIRECTOR)
    assert engine.approvals.decide(cid, felipe, "reject", "No procede")["status"] == "rejected"
    with pytest.raises(ApprovalError):
        engine.approvals.decide(cid, staff(engine, config.ROLE_CEO), "approve")
    with pytest.raises(ApprovalError):
        engine.approvals.send(cid, felipe)
    with pytest.raises(ApprovalError):
        engine.approvals.decide(cid, None, "approve")
    with pytest.raises(ApprovalError):
        engine.approvals.decide(cid, {"id": "agent:supplier-supervisor", "role": config.ROLE_OPS_DIRECTOR}, "approve")


def test_agents_have_no_tool_to_send_or_approve(engine):
    for agent in config.AGENT_PERMISSIONS:
        box = Toolbox(engine.store, agent, "r")
        for tool in ("send_to_supplier", "approve_communication"):
            with pytest.raises(PermissionDenied):
                box.use(tool, "BR-S05", lambda: None)
    sent = [e for e in engine.store.events(500) if e["action"] == "communication_sent"]
    assert not sent


# ============================================================ datos sensibles
def test_redact_covers_bank_phone_and_personal_email_but_not_internal_mail():
    text = "Cuenta de ahorros No. 123-456789-01; teléfono +57 300 123 4567; correo juan.perez.personal@gmail.com; felipe.guerrero@brasaland-demo.com"
    clean, kinds = redact(text)
    assert set(kinds) == {"datos_bancarios", "telefono", "correo"}
    assert "123-456789-01" not in clean and "300 123" not in clean and "gmail" not in clean and "felipe.guerrero@brasaland-demo.com" in clean
    assert redact("Tel. (305) 555-0142 y account no. 0012345678, routing 021000021")[0].count("[dato sensible omitido]") >= 2
    assert not contains_sensitive("COP 1.276.800.000 vence el 2027-03-25 en 120 días, IPC 5,2%")


def _all_text(engine) -> str:
    parts = [Path(engine.store.path).read_bytes().decode("latin-1")]
    for table in ("terms", "events", "messages", "alerts", "communications", "approvals", "notices", "prices", "contracts", "meta"):
        parts.append(repr(engine.store.q(f"SELECT * FROM {table}")))
    return "\n".join(parts)


def test_sensitive_data_never_reaches_db_logs_messages_answers_briefs_or_drafts(engine, caplog):
    caplog.set_level(logging.DEBUG)
    outputs = [engine.ask(q).model_dump_json() for q in (
        "¿La subida de Sunshine Prime Meats está permitida por el contrato?", "¿Qué dice el contrato de Carnes del Valle?", "¿Qué dice el contrato de Avícola Antioquia?",
        "¿Qué dice el contrato de Brava Beverages?", "¿Cuál es el preaviso de Avícola Antioquia?")]
    for sid in ("BR-S01", "BR-S05", "BR-S02", "BR-S08"):
        r = engine.brief(sid, draft_message=True)
        outputs += [r.model_dump_json(), engine.contract_view(sid).model_dump_json(), engine.price_view(sid).model_dump_json()]
    outputs += [repr(engine.approvals.listing()), repr(engine.alerts.listing()), caplog.text, _all_text(engine)]
    blob = "\n".join(outputs)
    for secret in SENSITIVE_VALUES:
        assert secret not in blob, f"se filtró un dato sensible: {secret}"


def test_sensitive_text_in_a_comment_or_draft_is_redacted_before_saving(engine):
    cid = engine.brief("BR-S02", draft_message=True).brief["communication_id"]
    engine.approvals.decide(cid, staff(engine, config.ROLE_OPS_DIRECTOR), "reject", "Llamar al +57 300 123 4567 o escribir a juan.perez.personal@gmail.com")
    blob = repr(engine.approvals.get(cid)) + _all_text(engine)
    assert "300 123 4567" not in blob and "juan.perez.personal" not in blob and "[dato sensible omitido]" in blob
    engine.approvals.draft("BR-S02", "Asunto", "Cuenta No. 310-998877-22", config.SUPERVISOR_ID)
    assert "310-998877-22" not in _all_text(engine)
