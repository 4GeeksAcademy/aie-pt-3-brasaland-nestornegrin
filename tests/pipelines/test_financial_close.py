"""Cierre financiero mensual: herramientas deterministas, ingesta, agente, revisión/rechazo, distribución, programación y datos sensibles."""
from __future__ import annotations

import csv
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from data.pipelines.financial_close import config, generate, ingest, schedule, tools
from data.pipelines.financial_close.agent import AgentPermissionError, FinancialCloseAgent
from data.pipelines.financial_close.sensitive import contains_sensitive
from data.pipelines.financial_close.store import CloseStore, DataStore
from data.pipelines.financial_close.workflow import CloseEngine, WorkflowError

D = Decimal
LOAD = date(2026, 11, 25)
PERIOD = "2026-10"


def build(tmp_path: Path, name: str = "a", mutate=None):
    src = tmp_path / f"{name}-csv"
    generate.generate(src, LOAD)
    if mutate:
        mutate(src)
    eng = CloseEngine(DataStore(tmp_path / f"{name}-data.db"), CloseStore(tmp_path / f"{name}-close.db"))
    eng.load_period(src, PERIOD)
    return eng, src


@pytest.fixture
def eng(tmp_path):
    return build(tmp_path)[0]


@pytest.fixture
def felipe(eng):
    return eng.close.staff("s-felipe")


def rewrite(path: Path, fn):
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    cols = list(rows[0].keys())
    rows = fn(rows)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


# ------------------------------------------------------------------ herramientas deterministas
def test_sum_amounts_and_currency_mix():
    assert tools.sum_amounts([(D("10.10"), "USD"), (D("20.20"), "USD")]) == (D("30.30"), "USD")
    with pytest.raises(tools.CurrencyMixError):
        tools.sum_amounts([(D("1"), "USD"), (D("1"), "COP")])


def test_variance_abs_and_pct_exact():
    assert tools.variance_abs(D("110656000"), D("106400000")) == D("4256000")
    assert tools.variance_pct(D("110656000"), D("106400000")) == D("4")
    assert tools.variance_pct(D("5"), D("0")) is None
    assert tools.q1(tools.variance_pct(D("205000"), D("230000"))) == D("-10.9")


def test_threshold_is_inclusive_and_uses_unrounded_value():
    assert tools.is_relevant_deviation(D("5")) and tools.is_relevant_deviation(D("-5"))
    assert not tools.is_relevant_deviation(D("4.99")) and not tools.is_relevant_deviation(D("4")) and not tools.is_relevant_deviation(None)
    assert not tools.is_relevant_deviation(tools.variance_pct(D("104.999"), D("100")))     # 4,999 % no se redondea a 5


def test_currency_conversion_uses_briefing_rate():
    assert tools.convert_currency(D("4000"), "COP", "USD") == D("1")
    assert tools.to_usd(D("1090000000"), "COP") == D("272500")
    assert tools.to_usd(D("10"), "USD") == D("10")
    assert tools.consolidate_usd([(D("1090000000"), "COP"), (D("205000"), "USD")]) == D("477500")


def test_price_volume_effects_add_up_exactly():
    price, vol = tools.price_volume_effect(D("8.064"), D("2400"), D("7.20"), D("2400"))
    assert (price, vol) == (D("2073.6"), D("0"))
    p2, v2 = tools.price_volume_effect(D("12"), D("90"), D("10"), D("100"))
    assert p2 + v2 == D("12") * D("90") - D("10") * D("100")


def test_parse_purchase_reads_supplier_price_and_quantity():
    p = tools.parse_purchase("Compra a proveedor Sunshine Prime Meats; precio unitario 8.064 USD/lb; cantidad 600 lb")
    assert p == {"supplier": "Sunshine Prime Meats", "unit_price": D("8.064"), "currency": "USD", "unit": "lb", "quantity": D("600")}
    assert tools.parse_purchase("Gasto de marketing – factura MK-1022") is None


# ------------------------------------------------------------------ datos y ingesta
def test_generated_ledger_sums_exactly_to_the_briefing(tmp_path):
    src = tmp_path / "csv"
    generate.generate(src, LOAD)
    rows = list(csv.DictReader((src / "ledger.csv").open(encoding="utf-8")))
    assert list(rows[0]) == ["entry_id", "date", "country", "category", "description", "currency", "amount", "source_ref"]
    for line in config.LINES:
        recs = [D(r["amount"]) for r in rows if r["country"] == config.COUNTRIES[line.country][0] and r["category"] == line.category]
        if line.actual is None:
            assert recs == []
        else:
            assert len(recs) >= 2
            assert abs(sum(recs)) == line.actual


def test_closing_period_is_last_full_month():
    assert generate.closing_period(date(2026, 11, 25)) == "2026-10" and generate.closing_period(date(2027, 1, 3)) == "2026-12"


def test_doubtful_records_are_marked_and_excluded(tmp_path):
    def mutate(src):
        def fn(rows):
            rows[0]["amount"] = "no-es-numero"
            rows[1]["entry_id"] = rows[2]["entry_id"]            # duplicado
            rows[3]["date"] = "2025-01-05"                        # fuera del periodo
            return rows
        rewrite(src / "ledger.csv", fn)
    eng, _ = build(tmp_path, mutate=mutate)
    rep = eng.run_close(PERIOD)["content"]
    kinds = [m["kind"] for m in rep["missing"]]
    assert kinds.count("doubtful_record") >= 3
    assert all(f["sources"] for f in rep["figures"].values() if f["id"].endswith(".ACT"))


# ------------------------------------------------------------------ agente: resultados esperados del briefing
def lines(rep, cc):
    return {l["category"]: l for l in rep["countries"][cc]["lines"]}


def test_expected_deviations_from_the_briefing(eng):
    rep = eng.run_close(PERIOD)["content"]
    pcts = {(d["country"], d["category"]): d["pct"] for d in rep["deviations"]}
    assert pcts == {("FL", "Ingresos por ventas"): "-10.9", ("FL", "Carne de res"): "12.0", ("CO", "Pollo"): "9.0", ("FL", "Bebidas"): "6.0", ("FL", "Marketing"): "72.2"}
    assert not lines(rep, "CO")["Carne de res"]["relevant"] and lines(rep, "CO")["Carne de res"]["pct"] == "4.0"
    assert lines(rep, "CO")["Ingresos por ventas"]["pct"] == "-2.7" and not lines(rep, "CO")["Ingresos por ventas"]["relevant"]


def test_hypotheses_are_backed_by_data(eng):
    rep = eng.run_close(PERIOD)["content"]
    by = {(d["country"], d["category"]): d for d in rep["deviations"]}
    rev = by[("FL", "Ingresos por ventas")]
    assert rev["supported"] and "cubiertos" in rev["hypothesis"] and "-10,9%" in rev["hypothesis"] and "ticket medio" in rev["hypothesis"]
    for key, supplier in ((("FL", "Carne de res"), "Sunshine Prime Meats"), (("CO", "Pollo"), "Avícola Antioquia"), (("FL", "Bebidas"), "Brava Beverages FL")):
        d = by[key]
        assert d["supported"] and supplier in d["hypothesis"] and "precio unitario" in d["hypothesis"]
    assert "misma cantidad" in by[("CO", "Pollo")]["hypothesis"]
    mkt = by[("FL", "Marketing")]
    assert not mkt["supported"] and "no indican el motivo" in mkt["hypothesis"] and "no inventa" in mkt["hypothesis"]


def test_price_and_quantity_effects_explain_the_whole_deviation(eng):
    rep = eng.run_close(PERIOD)["content"]
    f = rep["figures"]
    for k, line in (("FL.BEEF", "FL"), ("CO.CHICKEN", "CO"), ("FL.DRINKS", "FL")):
        eff = D(f[f"{k}.EFF.PRICE"]["value"]) + D(f[f"{k}.EFF.QTY"]["value"])
        assert eff == D(f[f"{k}.VAR"]["value"])


def test_missing_line_is_declared_and_never_zero_or_minus_100(eng):
    rep = eng.run_close(PERIOD)["content"]
    util = lines(rep, "FL")["Servicios"]
    assert util["actual"] is None and util["pct"] is None and not util["relevant"] and util["status"] == "missing"
    assert "FL.UTIL.ACT" not in rep["figures"]
    assert any(m["kind"] == "missing_line" and "Florida" in m["text"] and "SIN REGISTROS" in m["text"] for m in rep["missing"])
    assert "-100" not in " ".join(d["hypothesis"] for d in rep["deviations"]) and all(d["category"] != "Servicios" for d in rep["deviations"])
    md = eng.latest(PERIOD)["markdown"]
    assert "SIN REGISTROS" in md and "-100" not in md.replace("−100 %", "")


def test_consolidated_figures_use_the_reference_rate(eng):
    rep = eng.run_close(PERIOD)["content"]
    v = rep["consolidated"]["values"]
    assert D(v["INC.ACT"]) == D("1090000000") / 4000 + D("205000") and D(v["INC.BUD"]) == D("1120000000") / 4000 + D("230000")
    assert rep["fx"] == "1 USD = 4.000 COP" and not rep["consolidated"]["complete"]
    assert D(v["RES.CMPBUD"]) == D(v["INC.BUD"]) - D(v["EXP.CMPBUD"])


def test_report_has_the_six_sections_in_order(eng):
    md = eng.run_close(PERIOD)["markdown"]
    heads = [l for l in md.splitlines() if l.startswith("## ")]
    assert [h.split(". ", 1)[1] for h in heads] == ["Resumen ejecutivo", "Resultado consolidado en USD", "Resultado por país (moneda local)",
                                                     "Desviaciones relevantes", "Datos faltantes o dudosos", "Anexo de trazabilidad"]
    summary = eng.run_close(PERIOD)["content"]["summary"]
    assert 1 <= len(summary) <= 5
    assert "1 USD = 4.000 COP" in md


# ------------------------------------------------------------------ determinismo y trazabilidad
def test_two_runs_give_identical_figures(tmp_path):
    a, _ = build(tmp_path, "a")
    b, _ = build(tmp_path, "b")
    ra, rb = a.run_close(PERIOD), b.run_close(PERIOD)
    assert ra["content_hash"] == rb["content_hash"]
    assert ra["content"]["figures"] == rb["content"]["figures"]
    again = FinancialCloseAgent(a.data, a.close).close_period(PERIOD)
    assert again["content_hash"] == ra["content_hash"]


def test_run_close_is_idempotent_per_period(eng):
    assert eng.run_close(PERIOD)["id"] == eng.run_close(PERIOD)["id"] and len(eng.list_reports()) == 1


def test_every_figure_is_traceable_to_its_origin(eng):
    rep = eng.run_close(PERIOD)
    for fid, f in rep["content"]["figures"].items():
        assert f["sources"], fid
    f = eng.figure(rep["id"], "FL.MKT.ACT")
    assert [r["entry_id"] for r in f["records"]] == [s["entry_id"] for s in f["sources"]] and len(f["records"]) == 3
    assert sum(D(r["amount"]) for r in f["records"]) == D("-15500")
    cons = eng.figure(rep["id"], "CONS.INC.ACT")
    assert len(cons["records"]) == 8 and all(r["entry_id"] for r in cons["records"])
    assert all(e in rep["markdown"] for e in [r["entry_id"] for r in f["records"]])      # el anexo los lista
    with pytest.raises(WorkflowError):
        eng.figure(rep["id"], "NO.EXISTE")


# ------------------------------------------------------------------ revisión y distribución
def test_nothing_is_distributed_without_approval(eng, felipe):
    rep = eng.run_close(PERIOD)
    assert rep["status"] == "pending_review"
    kinds = [m["kind"] for m in eng.close.messages()]
    assert kinds == ["review_request"] and eng.close.messages()[0]["recipient_id"] == "s-felipe"
    with pytest.raises(WorkflowError) as e:
        eng.distribute(rep["id"])
    assert e.value.status == 409


def test_only_the_reviewer_can_decide(eng):
    rep = eng.run_close(PERIOD)
    for sid in ("s-mariana", "s-nicolas", "s-lucia"):
        with pytest.raises(WorkflowError) as e:
            eng.review(rep["id"], eng.close.staff(sid), "approve")
        assert e.value.status == 403
    assert eng.get(rep["id"])["status"] == "pending_review"


def test_approval_distributes_to_the_seven_recipients_once(eng, felipe):
    rep = eng.run_close(PERIOD)
    out = eng.review(rep["id"], felipe, "approve", "ok")
    assert out["status"] == "distributed"
    sent = [m for m in eng.close.messages(rep["id"]) if m["kind"] == "distribution"]
    assert sorted(m["recipient_id"] for m in sent) == sorted(config.RECIPIENT_IDS) and len(sent) == 7
    names = {config.STAFF[i][1] for i in range(7)}
    assert names == {"Mariana Restrepo", "Felipe Guerrero", "Nicolás Park", "Lucía Fernández", "Camila Ospina", "Ashley Turner", "Jake Morrison"}
    assert eng.distribute(rep["id"])["status"] == "distributed" and len([m for m in eng.close.messages(rep["id"]) if m["kind"] == "distribution"]) == 7
    with pytest.raises(WorkflowError) as e:
        eng.review(rep["id"], felipe, "approve")
    assert e.value.status == 409


def test_rejection_requires_comments_and_creates_a_new_version(eng, felipe):
    v1 = eng.run_close(PERIOD)
    with pytest.raises(WorkflowError):
        eng.review(v1["id"], felipe, "reject", "  ")
    v2 = eng.review(v1["id"], felipe, "reject", "Detalla Marketing de Florida\nRevisa el tono de cambio del cielo")
    assert eng.get(v1["id"])["status"] == "rejected"
    assert v2["version"] == 2 and v2["status"] == "pending_review" and v2["id"] != v1["id"] and v2["based_on_review"]
    assert [m for m in eng.close.messages() if m["kind"] == "distribution"] == []
    rev = v2["content"]["revision"]
    assert rev[0]["handled"] and rev[0]["detail"][0]["label"] == "Marketing" and len(rev[0]["detail"][0]["records"]) == 3
    assert not rev[1]["handled"]
    assert "Detalle ampliado" in v2["markdown"] and "NO ATENDIDO" in v2["markdown"]
    assert v2["content"]["figures"] == v1["content"]["figures"]                 # los comentarios no cambian las cifras
    again = eng.review(v2["id"], felipe, "approve")
    assert again["status"] == "distributed" and again["version"] == 2


def test_visibility_before_and_after_approval(eng, felipe):
    rep = eng.run_close(PERIOD)
    assert eng.can_view(rep, felipe) and not eng.can_view(rep, eng.close.staff("s-mariana"))
    done = eng.review(rep["id"], felipe, "approve")
    assert eng.can_view(done, eng.close.staff("s-mariana")) and eng.can_view(done, eng.close.staff("s-jake"))


# ------------------------------------------------------------------ incompleto
def test_incomplete_period_declares_what_is_missing(tmp_path):
    def mutate(src):
        rewrite(src / "ledger.csv", lambda rows: [r for r in rows if not (r["country"] == "Florida" and r["category"] == "Marketing")])
        rewrite(src / "operations.csv", lambda rows: [r for r in rows if not (r["country"] == "Florida" and r["metric"].startswith("covers"))])
    eng, _ = build(tmp_path, mutate=mutate)
    rep = eng.run_close(PERIOD)["content"]
    texts = " | ".join(m["text"] for m in rep["missing"])
    assert "Florida · Marketing" in texts and "Florida · Servicios" in texts and "indicadores operativos" in texts
    assert all(d["category"] != "Marketing" or d["country"] != "FL" for d in rep["deviations"])
    rev = next(d for d in rep["deviations"] if d["category"] == config.INCOME)
    assert not rev["supported"] and "Hipótesis no disponible" in rev["hypothesis"]


# ------------------------------------------------------------------ agente: identidad, solo lectura y registro
def test_agent_is_read_only_and_denials_are_logged(eng):
    agent = FinancialCloseAgent(eng.data, eng.close)
    for forbidden in sorted(config.FORBIDDEN_FOR_AGENT):
        with pytest.raises(AgentPermissionError):
            agent.use(forbidden, "x", lambda: None)
    assert [e["action"] for e in eng.close.events() if e["action"] == "denied"].__len__() == len(config.FORBIDDEN_FOR_AGENT)
    with pytest.raises(Exception):
        eng.data.readonly_query("DELETE FROM records")
    with pytest.raises(Exception):
        eng.data.readonly_query("INSERT INTO loads(period) VALUES('x')")


def test_agent_actions_are_logged_as_automated_process(eng, felipe):
    rep = eng.run_close(PERIOD)
    eng.review(rep["id"], felipe, "approve")
    events = eng.close.events(2000)
    agent_events = [e for e in events if e["actor_id"] == config.AGENT_ID]
    assert agent_events and {e["actor_type"] for e in agent_events} == {"automated_process"}
    assert {"read", "tool:sum_amounts", "report_created", "distributed"} <= {e["action"] for e in agent_events}
    human = [e for e in events if e["actor_type"] == "user"]
    assert human and human[0]["actor_id"] == "s-felipe" and human[0]["action"] == "review_approve"


# ------------------------------------------------------------------ datos sensibles
def test_sensitive_data_never_reaches_stores_logs_or_messages(tmp_path):
    def mutate(src):
        def fn(rows):
            rows.append({**rows[0], "entry_id": "L-X-1", "description": "Nómina de Juan Pérez salario individual 4.500.000 COP", "category": "Nómina", "country": "Colombia", "currency": "COP", "amount": "-100"})
            return rows
        rewrite(src / "ledger.csv", fn)
    eng, src = build(tmp_path, mutate=mutate)
    assert any(v in (src / "ledger.csv").read_text(encoding="utf-8") for v in generate.SENSITIVE_VALUES)     # el origen SÍ los trae
    rep = eng.run_close(PERIOD)
    eng.review(rep["id"], eng.close.staff("s-felipe"), "reject", f"Revisa {generate.SENSITIVE_VALUES[0]} en Marketing")
    eng2 = eng.latest(PERIOD)
    eng.review(eng2["id"], eng.close.staff("s-felipe"), "approve")
    blob = json.dumps([eng.data.q("SELECT * FROM records"), eng.close.q("SELECT * FROM reports"), eng.close.q("SELECT * FROM events"),
                       eng.close.q("SELECT * FROM messages"), eng.close.q("SELECT * FROM reviews")], ensure_ascii=False)
    for value in generate.SENSITIVE_VALUES:
        assert value not in blob, value
    assert "Juan Pérez" not in blob and "4.500.000 COP" not in blob
    assert not contains_sensitive(blob)
    assert any(r["status"] == "doubtful" for r in eng.data.q("SELECT status FROM records WHERE entry_id='L-X-1'"))     # nómina por persona = dudoso


# ------------------------------------------------------------------ programación
def test_third_business_day_at_0600_medellin():
    assert schedule.third_business_day(2026, 11) == date(2026, 11, 4)        # 2 (lun), 3, 4 (mié)
    assert schedule.third_business_day(2026, 8) == date(2026, 8, 5)          # 1 = sábado → 3, 4, 5
    assert schedule.third_business_day(2027, 1) == date(2027, 1, 5)          # 1 = viernes → 1, 4, 5
    at = schedule.run_at(2026, 11)
    assert (at.hour, at.minute, at.utcoffset().total_seconds()) == (6, 0, -5 * 3600)


def test_tick_runs_once_per_period_and_only_when_due(tmp_path):
    eng, src = build(tmp_path)
    tz = schedule.TZ
    assert not schedule.tick(eng, datetime(2026, 11, 4, 5, 59, tzinfo=tz), src)["ran"] and eng.list_reports() == []
    assert schedule.tick(eng, datetime(2026, 11, 4, 6, 0, tzinfo=tz), src)["ran"]
    assert not schedule.tick(eng, datetime(2026, 11, 4, 7, 0, tzinfo=tz), src)["ran"] and not schedule.tick(eng, datetime(2026, 11, 20, tzinfo=tz), src)["ran"]
    assert len(eng.list_reports()) == 1 and eng.list_reports()[0]["period"] == "2026-10"
    assert eng.list_reports()[0]["status"] == "pending_review"
    assert any(e["actor_id"] == "scheduler" for e in eng.close.events())


def test_holidays_are_configurable(monkeypatch):
    monkeypatch.setattr(config, "HOLIDAYS", frozenset({"2026-11-03"}))
    assert schedule.third_business_day(2026, 11) == date(2026, 11, 5)


# ------------------------------------------------------------------ regresiones del feedback del profesor
EXPECTED_LINES = {(l.country, l.category) for l in config.LINES}


def test_every_figure_always_has_a_source(eng, tmp_path):
    for rep in (eng.run_close(PERIOD)["content"], build(tmp_path, "inc", lambda s: rewrite(s / "ledger.csv", lambda r: r[:5]))[0].run_close(PERIOD)["content"]):
        assert all(f["sources"] and f["value"] is not None for f in rep["figures"].values())


def test_line_missing_from_budget_and_ledger_is_declared(tmp_path):
    def mutate(src):
        rewrite(src / "ledger.csv", lambda rows: [r for r in rows if not (r["country"] == "Florida" and r["category"] == "Pollo")])
        rewrite(src / "budget.csv", lambda rows: [r for r in rows if not (r["country"] == "Florida" and r["category"] == "Pollo")])
    eng, _ = build(tmp_path, mutate=mutate)
    rep = eng.run_close(PERIOD)["content"]
    line = {l["category"]: l for l in rep["countries"]["FL"]["lines"]}["Pollo"]          # la partida NO se omite
    assert line["status"] == "missing" and line["actual"] is None and line["budget"] is None
    assert any(m["kind"] == "missing_line_and_budget" and "Florida · Pollo" in m["text"] and "presupuesto" in m["text"] for m in rep["missing"])
    assert not any(k.startswith("FL.CHICKEN") for k in rep["figures"])
    assert "Florida · Pollo" in " ".join(rep["summary"]) and "ninguno" not in rep["summary"][3]
    md = eng.run_close(PERIOD)["markdown"]
    assert "SIN PRESUPUESTO" in md and "SIN REGISTROS" in md


def test_empty_period_declares_every_expected_line_and_emits_no_figures(tmp_path):
    def mutate(src):
        for name in ("ledger.csv", "budget.csv", "operations.csv"):
            header = (src / name).read_text(encoding="utf-8").splitlines()[0]
            (src / name).write_text(header + "\n", encoding="utf-8")
    eng, _ = build(tmp_path, mutate=mutate)
    rep = eng.run_close(PERIOD)["content"]
    assert rep["figures"] == {}                                                        # ni ceros ni cifras sin origen
    declared = {(cc, l["category"]) for cc, c in rep["countries"].items() for l in c["lines"]}
    assert declared == EXPECTED_LINES
    assert len([m for m in rep["missing"] if m["kind"] == "missing_line_and_budget"]) == len(EXPECTED_LINES)
    assert all(l["actual"] is None and l["budget"] is None for c in rep["countries"].values() for l in c["lines"])
    assert rep["consolidated"]["values"]["RES.ACT"] is None and rep["deviations"] == []
    text = " ".join(rep["summary"])
    assert "NO se puede calcular" in text and "ninguno" not in rep["summary"][3] and len(rep["summary"]) <= 5
    md = eng.run_close(PERIOD)["markdown"]
    assert "sin dato" in md and "NO CALCULABLE" in md and " 0,00 " not in md.split("## 4.")[0].split("## 2.")[1]


def test_figure_origin_never_mixes_periods(tmp_path):
    eng, _ = build(tmp_path)
    other = tmp_path / "sep-csv"
    generate.generate(other, date(2026, 10, 15))                                       # mes de cierre 2026-09: mismos archivos y filas
    eng.load_period(other, "2026-09")
    rep = eng.run_close(PERIOD)
    for fid in ("FL.MKT.ACT", "CONS.INC.ACT", "FL.BEEF.ACT", "FL.REV.PCT"):
        f = eng.figure(rep["id"], fid)
        assert f["records"] and all(r["date"] is None or r["date"].startswith("2026-10") for r in f["records"])
        assert len(f["records"]) == len(f["sources"])
        assert all((r["entry_id"] or "").find("2026-09") < 0 for r in f["records"])
    sep = eng.run_close("2026-09")
    assert all((r["entry_id"] or "").find("2026-10") < 0 for r in eng.figure(sep["id"], "FL.MKT.ACT")["records"])


def test_malformed_amount_with_bank_account_never_leaks(tmp_path):
    secret = generate.SENSITIVE_VALUES[0]
    def mutate(src):
        def fn(rows):
            rows[0]["amount"] = f"12,5x cuenta {secret}"
            rows[1]["description"] = f"Ventas; cuenta {secret}"
            return rows
        rewrite(src / "ledger.csv", fn)
    eng, _ = build(tmp_path, mutate=mutate)
    rep = eng.run_close(PERIOD)
    eng.review(rep["id"], eng.close.staff("s-felipe"), "approve")
    tables = {t: eng.close.q(f"SELECT * FROM {t}") for t in ("reports", "events", "messages", "reviews")} | {"records": eng.data.q("SELECT * FROM records")}
    for name, rows in tables.items():
        assert secret not in json.dumps(rows, ensure_ascii=False), name
    assert any("importe no numérico" in m["text"] for m in rep["content"]["missing"] if m["kind"] == "doubtful_record")
    assert secret not in json.dumps(eng.get(rep["id"]), ensure_ascii=False)
