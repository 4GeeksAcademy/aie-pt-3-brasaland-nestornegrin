"""AGENTE DE CIERRE (uno solo). Identidad propia (`agent:financial-close`), acceso de SOLO LECTURA a los datos financieros y únicamente las
herramientas de `config.AGENT_TOOLS`. Decide qué calcular, llama a las herramientas deterministas, detecta las desviaciones ≥ 5 % y redacta
una hipótesis para cada una, citando las cifras que la sostienen. Cada cifra del informe es una `Figure` con su origen. Cada acción queda
registrada como acción de un PROCESO AUTOMATIZADO. Lo que no hay se declara; nunca se trata como 0."""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from typing import Callable

from . import config, tools
from .store import CloseStore, DataStore

KEY = config.CATEGORY_KEY
_REASON_WORDS = re.compile(r"(?i)campa[ñn]a|evento|lanzamiento|promoci[oó]n|patrocinio|inauguraci[oó]n|publicidad digital|temporada|festival|motivo")
ACTOR_TYPE = "automated_process"


class AgentPermissionError(Exception):
    pass


class FinancialCloseAgent:
    agent_id = config.AGENT_ID

    def __init__(self, data: DataStore, close: CloseStore, narrator: "TemplateNarrator | None" = None):
        self.data, self.close, self.narrator = data, close, narrator or TemplateNarrator()
        self.figures: dict[str, dict] = {}

    # ------------------------------------------------------------ herramientas (única puerta: permiso + registro)
    def use(self, tool: str, subject: str, fn: Callable, detail: dict | None = None):
        if tool in config.FORBIDDEN_FOR_AGENT or tool not in config.AGENT_TOOLS:
            self.close.event(ACTOR_TYPE, self.agent_id, "denied", subject, {"tool": tool})
            raise AgentPermissionError(f"{self.agent_id} no tiene la herramienta «{tool}»")
        result = fn()
        self.close.event(ACTOR_TYPE, self.agent_id, f"tool:{tool}", subject, detail or {})
        return result

    def _read(self, tool: str, period: str, kind: str) -> list[dict]:
        rows = self.use(tool, f"{kind}:{period}", lambda: self.data.readonly_query("SELECT * FROM records WHERE period=? AND kind=? ORDER BY row", (period, kind)))
        self.close.event(ACTOR_TYPE, self.agent_id, "read", f"{kind}:{period}", {"rows": len(rows)})
        return rows

    # ------------------------------------------------------------ cifras con origen
    def _fig(self, fid: str, label: str, value: Decimal | None, unit: str, *, sources: list[dict] | None = None, components: list[str] | None = None,
             formula: str = "", status: str = "ok") -> str:
        refs = list(sources or [])
        for c in components or []:
            refs += self.figures[c]["sources"]
        uniq = {(s["file"], s["row"]): s for s in refs}
        self.figures[fid] = {"id": fid, "label": label, "value": None if value is None else str(value), "unit": unit, "formula": formula,
                             "components": components or [], "sources": [uniq[k] for k in sorted(uniq, key=lambda k: (k[0], k[1]))], "status": status}
        return fid

    @staticmethod
    def _src(rec: dict) -> dict:
        return {"file": rec["file"], "row": rec["row"], "entry_id": rec.get("entry_id") or None}

    # ------------------------------------------------------------ cierre del periodo
    def close_period(self, period: str) -> dict:
        self.figures = {}
        ledger_all, budget_all, ops_all = (self._read("read_ledger", period, "ledger"), self._read("read_budget", period, "budget"), self._read("read_operations", period, "operations"))
        ledger = [r for r in ledger_all if r["status"] == "valid"]
        doubtful = [r for r in ledger_all + budget_all + ops_all if r["status"] == "doubtful"]
        budget = {(r["country"], r["category"]): r for r in budget_all if r["status"] == "valid"}
        ops = {(r["country"], r["metric"]): r for r in ops_all if r["status"] == "valid"}
        by_line: dict[tuple, list[dict]] = {}
        for r in ledger:
            by_line.setdefault((r["country"], r["category"]), []).append(r)
        doubt_lines: dict[tuple, int] = {}
        for r in ledger_all + budget_all:
            if r["status"] == "doubtful" and r["country"] and r["category"]:
                doubt_lines[(r["country"], r["category"])] = doubt_lines.get((r["country"], r["category"]), 0) + 1

        missing: list[dict] = []
        countries: dict[str, dict] = {}
        for cc, (cname, cur) in config.COUNTRIES.items():
            lines = []
            for cat in config.CATEGORIES:
                b, recs = budget.get((cc, cat)), by_line.get((cc, cat), [])
                if b is None and not recs:
                    continue
                label = next((l.label for l in config.LINES if l.country == cc and l.category == cat), cat)
                k = f"{cc}.{KEY[cat]}"
                if b is None:
                    missing.append({"kind": "no_budget", "text": f"{cname} · {cat}: hay registros pero no hay presupuesto válido; no se calcula desviación.", "refs": [r["entry_id"] for r in recs]})
                    bud = None
                else:
                    bud = Decimal(b["amount"])
                    self._fig(f"{k}.BUD", f"{cname} · {label} · presupuesto", bud, cur, sources=[self._src(b)])
                act = None
                if recs:
                    total, _ = self.use("sum_amounts", f"{cc}.{cat}", lambda recs=recs: tools.sum_amounts((Decimal(r["amount"]), r["currency"]) for r in recs), {"records": len(recs)})
                    act = total if cat == config.INCOME else -total
                    status = "partial" if doubt_lines.get((cc, cat)) else "ok"
                    self._fig(f"{k}.ACT", f"{cname} · {label} · real", act, cur, sources=[self._src(r) for r in recs], formula="suma de los registros del libro", status=status)
                else:
                    status = "missing"
                    n = doubt_lines.get((cc, cat), 0)
                    missing.append({"kind": "missing_line", "text": f"{cname} · {label}: SIN REGISTROS en el libro" + (f" ({n} registro(s) dudoso(s) excluido(s))" if n else "") +
                                    f"; presupuesto {tools.fmt(bud)} {cur}. No se trata como 0 ni como una desviación del −100 %.", "refs": []})
                line = {"category": cat, "label": label, "currency": cur, "budget": None if bud is None else str(bud), "actual": None if act is None else str(act),
                        "status": status, "records": len(recs), "figs": {"bud": f"{k}.BUD" if bud is not None else None, "act": f"{k}.ACT" if act is not None else None},
                        "var_abs": None, "pct": None, "pct_exact": None, "relevant": False, "favorable": None}
                if status == "partial":
                    missing.append({"kind": "partial", "text": f"{cname} · {label}: cifra parcial, {doubt_lines[(cc, cat)]} registro(s) dudoso(s) excluido(s).", "refs": []})
                if bud is not None and act is not None:
                    comps = [f"{k}.BUD", f"{k}.ACT"]
                    va = self.use("variance", f"{cc}.{cat}", lambda: (tools.variance_abs(act, bud), tools.variance_pct(act, bud)))
                    abs_, pct = va
                    self._fig(f"{k}.VAR", f"{cname} · {label} · desviación", abs_, cur, components=comps, formula="real − presupuesto")
                    line["var_abs"], line["figs"]["var"] = str(abs_), f"{k}.VAR"
                    if pct is not None:
                        self._fig(f"{k}.PCT", f"{cname} · {label} · desviación %", tools.q1(pct), "%", components=comps, formula="(real − presupuesto) / presupuesto × 100")
                        line["pct"], line["pct_exact"], line["figs"]["pct"] = str(tools.q1(pct)), str(pct), f"{k}.PCT"
                        line["relevant"] = tools.is_relevant_deviation(pct)
                    if pct is not None:
                        line["favorable"] = (pct >= 0) if cat == config.INCOME else (pct <= 0)
                lines.append(line)
            countries[cc] = {"name": cname, "currency": cur, "lines": lines}
            self._country_totals(cc, countries[cc])

        for key, (cc, name) in {(k[0], k[1]): (k[0], k[1]) for k in ops}.items():     # indicadores operativos como cifras con origen
            pass
        for (cc, metric), r in ops.items():
            self._fig(f"{cc}.OPS.{metric}", f"{config.COUNTRIES[cc][0]} · {metric}", Decimal(r["amount"]), "", sources=[self._src(r)])

        consolidated = self._consolidate(countries)
        deviations = [self._deviation(cc, c, line, by_line, ops, missing) for cc, c in countries.items() for line in c["lines"] if line["relevant"]]
        for d in deviations:
            if next(l for l in countries[d["country"]]["lines"] if l["category"] == d["category"])["status"] == "partial":
                d["hypothesis"] = "ATENCIÓN: cifra PARCIAL (hay registros dudosos excluidos), la desviación puede estar distorsionada. " + d["hypothesis"]
                d["supported"] = False
        for r in doubtful:
            missing.append({"kind": "doubtful_record", "text": f"{r['file']} fila {r['row']}" + (f" ({r['entry_id']})" if r.get("entry_id") else "") + ": registro DUDOSO excluido de las cifras · " + "; ".join(json.loads(r["reasons"])),
                            "refs": [r["entry_id"]] if r.get("entry_id") else []})
        report = {"period": period, "language": config.LANGUAGE, "fx": f"1 USD = {tools.fmt(config.FX_COP_PER_USD, 0)} COP", "threshold_pct": str(config.THRESHOLD_PCT),
                  "countries": countries, "consolidated": consolidated, "deviations": deviations, "missing": missing, "figures": self.figures}
        report["summary"] = self.use("compose_report", period, lambda: self.narrator.summary(report), {"period": period})
        report["content_hash"] = content_hash(report)
        self.close.event(ACTOR_TYPE, self.agent_id, "report_prepared", period, {"figures": len(self.figures), "deviations": len(deviations), "missing": len(missing), "hash": report["content_hash"]})
        return report

    # ------------------------------------------------------------ totales por país
    def _country_totals(self, cc: str, country: dict) -> None:
        cur, name = country["currency"], country["name"]
        lines = country["lines"]
        inc = next((l for l in lines if l["category"] == config.INCOME), None)
        exp = [l for l in lines if l["category"] != config.INCOME]
        exp_act = [l for l in exp if l["actual"] is not None]
        comparable = [l for l in exp_act if l["budget"] is not None]
        totals: dict = {"currency": cur, "complete": all(l["actual"] is not None for l in exp) and all(l["budget"] is not None for l in lines)}
        if not totals["complete"]:
            totals["note"] = "Gastos reales PARCIALES (partidas sin registros o sin presupuesto); la comparación usa solo las partidas con ambos datos."
        if inc and inc["actual"] is not None:
            totals["income_act"], totals["income_bud"] = inc["actual"], inc["budget"]
        exp_a_comps = [l["figs"]["act"] for l in exp_act]
        exp_b_comps = [l["figs"]["bud"] for l in exp if l["budget"] is not None]
        cmp_b_comps = [l["figs"]["bud"] for l in comparable]
        cmp_a_comps = [l["figs"]["act"] for l in comparable]
        def total(items): return sum((Decimal(x) for x in items), Decimal(0))
        e_act = total(l["actual"] for l in exp_act)
        e_bud = total(l["budget"] for l in exp if l["budget"] is not None)
        e_cmp_a = total(l["actual"] for l in comparable)
        e_cmp_b = total(l["budget"] for l in comparable)
        self._fig(f"{cc}.EXP.ACT", f"{name} · gastos · real", e_act, cur, components=exp_a_comps, formula="suma de las partidas de gasto con registros", status="ok" if totals["complete"] else "partial")
        self._fig(f"{cc}.EXP.BUD", f"{name} · gastos · presupuesto", e_bud, cur, components=exp_b_comps, formula="suma de las partidas de gasto presupuestadas")
        self._fig(f"{cc}.EXP.CMPBUD", f"{name} · gastos · presupuesto comparable", e_cmp_b, cur, components=cmp_b_comps, formula="presupuesto solo de las partidas que tienen real")
        totals.update(expenses_act=str(e_act), expenses_bud=str(e_bud), expenses_cmp_bud=str(e_cmp_b),
                      figs={"exp_act": f"{cc}.EXP.ACT", "exp_bud": f"{cc}.EXP.BUD", "exp_cmpbud": f"{cc}.EXP.CMPBUD"})
        if inc and inc["actual"] is not None and inc["budget"] is not None:
            ia, ib = Decimal(inc["actual"]), Decimal(inc["budget"])
            self._fig(f"{cc}.RES.ACT", f"{name} · resultado · real", ia - e_act, cur, components=[inc["figs"]["act"], f"{cc}.EXP.ACT"], formula="ingresos − gastos")
            self._fig(f"{cc}.RES.BUD", f"{name} · resultado · presupuesto", ib - e_bud, cur, components=[inc["figs"]["bud"], f"{cc}.EXP.BUD"], formula="ingresos − gastos presupuestados")
            self._fig(f"{cc}.RES.CMPBUD", f"{name} · resultado · presupuesto comparable", ib - e_cmp_b, cur, components=[inc["figs"]["bud"], f"{cc}.EXP.CMPBUD"], formula="ingresos − gastos presupuestados comparables")
            res_act = ia - e_act
            res_cmp = ib - e_cmp_b
            totals.update(result_act=str(res_act), result_bud=str(ib - e_bud), result_cmp_bud=str(res_cmp), result_var_abs=str(res_act - res_cmp))
            totals["figs"].update(res_act=f"{cc}.RES.ACT", res_bud=f"{cc}.RES.BUD", res_cmpbud=f"{cc}.RES.CMPBUD")
            totals["expenses_var_abs"] = str(e_act - e_cmp_a) if not totals["complete"] else str(e_act - e_bud)
        country["totals"] = totals

    # ------------------------------------------------------------ consolidado en USD
    def _consolidate(self, countries: dict) -> dict:
        out: dict = {"fx": f"1 USD = {tools.fmt(config.FX_COP_PER_USD, 0)} COP", "currency": "USD", "figs": {}}
        parts = {}
        for name, (a_key, b_key) in {"income": ("income_act", "income_bud"), "expenses": ("expenses_act", "expenses_cmp_bud")}.items():
            pass
        def usd(cc, field):
            t = countries[cc]["totals"]
            return None if t.get(field) is None else tools.to_usd(Decimal(t[field]), t["currency"])
        complete = all(c["totals"]["complete"] for c in countries.values())
        spec = {"INC.ACT": ("income_act", "REV.ACT"), "INC.BUD": ("income_bud", "REV.BUD"), "EXP.ACT": ("expenses_act", "EXP.ACT"), "EXP.BUD": ("expenses_bud", "EXP.BUD"),
                "EXP.CMPBUD": ("expenses_cmp_bud", "EXP.CMPBUD")}
        vals: dict[str, Decimal] = {}
        for fid, (field, comp) in spec.items():
            items = [(Decimal(c["totals"][field]), c["totals"]["currency"]) for c in countries.values() if c["totals"].get(field) is not None]
            comps = [f"{cc}.{comp}" for cc, c in countries.items() if c["totals"].get(field) is not None]
            v = self.use("consolidate", f"CONS.{fid}", lambda items=items: tools.consolidate_usd(items))
            vals[fid] = v
            self._fig(f"CONS.{fid}", f"Consolidado USD · {fid}", v, "USD", components=comps, formula=f"cada país convertido a USD ({out['fx']}) y sumado", status="ok" if complete or fid.startswith("INC") else "partial")
        res_act, res_bud, res_cmp = vals["INC.ACT"] - vals["EXP.ACT"], vals["INC.BUD"] - vals["EXP.BUD"], vals["INC.BUD"] - vals["EXP.CMPBUD"]
        self._fig("CONS.RES.ACT", "Consolidado USD · resultado real", res_act, "USD", components=["CONS.INC.ACT", "CONS.EXP.ACT"], formula="ingresos − gastos", status="ok" if complete else "partial")
        self._fig("CONS.RES.BUD", "Consolidado USD · resultado presupuesto", res_bud, "USD", components=["CONS.INC.BUD", "CONS.EXP.BUD"], formula="ingresos − gastos presupuestados")
        self._fig("CONS.RES.CMPBUD", "Consolidado USD · resultado presupuesto comparable", res_cmp, "USD", components=["CONS.INC.BUD", "CONS.EXP.CMPBUD"], formula="ingresos − gastos presupuestados comparables")
        out["complete"] = complete
        out["values"] = {k: str(v) for k, v in vals.items()} | {"RES.ACT": str(res_act), "RES.BUD": str(res_bud), "RES.CMPBUD": str(res_cmp)}
        out["rows"] = [
            {"label": "Ingresos", "act": str(vals["INC.ACT"]), "bud": str(vals["INC.BUD"]), "cmp_bud": str(vals["INC.BUD"]), "figs": ["CONS.INC.ACT", "CONS.INC.BUD"]},
            {"label": "Gastos" + ("" if complete else " (parciales)"), "act": str(vals["EXP.ACT"]), "bud": str(vals["EXP.BUD"]), "cmp_bud": str(vals["EXP.CMPBUD"]), "figs": ["CONS.EXP.ACT", "CONS.EXP.BUD", "CONS.EXP.CMPBUD"]},
            {"label": "Resultado" + ("" if complete else " (parcial)"), "act": str(res_act), "bud": str(res_bud), "cmp_bud": str(res_cmp), "figs": ["CONS.RES.ACT", "CONS.RES.BUD", "CONS.RES.CMPBUD"]},
        ]
        if not complete:
            out["note"] = ("Gastos y resultado reales PARCIALES: faltan partidas sin registros. La desviación se calcula frente al presupuesto comparable "
                           "(solo las partidas que tienen dato real); el resultado real no es comparable con el presupuesto completo.")
        return out

    # ------------------------------------------------------------ desviaciones relevantes + hipótesis
    def _deviation(self, cc: str, country: dict, line: dict, by_line: dict, ops: dict, missing: list[dict]) -> dict:
        cat, cname, cur = line["category"], country["name"], country["currency"]
        k = f"{cc}.{KEY[cat]}"
        recs = by_line.get((cc, cat), [])
        dev = {"country": cc, "country_name": cname, "category": cat, "label": line["label"], "currency": cur, "pct": line["pct"], "var_abs": line["var_abs"],
               "favorable": line["favorable"], "figs": [line["figs"]["bud"], line["figs"]["act"], line["figs"]["var"], line["figs"]["pct"]], "kind": "other",
               "hypothesis": "", "supported": False, "evidence": []}
        pct = Decimal(line["pct_exact"])
        if cat == config.INCOME:
            dev["kind"] = "revenue"
            cov_b, cov_a = ops.get((cc, "covers_served_budget")), ops.get((cc, "covers_served_actual"))
            tk_b, tk_a = ops.get((cc, "avg_ticket_budget")), ops.get((cc, "avg_ticket_actual"))
            if not all((cov_b, cov_a, tk_b, tk_a)):
                dev["hypothesis"] = "Hipótesis no disponible: faltan indicadores operativos (cubiertos o ticket medio) en operations.csv."
                missing.append({"kind": "missing_indicator", "text": f"{cname} · Ingresos: faltan indicadores operativos; no se puede sostener una hipótesis.", "refs": []})
                return dev
            ev = [f"{cc}.OPS.covers_served_budget", f"{cc}.OPS.covers_served_actual", f"{cc}.OPS.avg_ticket_budget", f"{cc}.OPS.avg_ticket_actual"]
            covers = self.use("variance", f"{cc}.covers", lambda: tools.pct_change(Decimal(cov_b["amount"]), Decimal(cov_a["amount"])))
            ticket = tools.pct_change(Decimal(tk_b["amount"]), Decimal(tk_a["amount"]))
            self._fig(f"{cc}.OPS.covers_pct", f"{cname} · cubiertos · variación %", tools.q1(covers), "%", components=ev[:2], formula="(real − presupuesto) / presupuesto × 100")
            self._fig(f"{cc}.OPS.ticket_pct", f"{cname} · ticket medio · variación %", tools.q1(ticket), "%", components=ev[2:], formula="(real − presupuesto) / presupuesto × 100")
            ev += [f"{cc}.OPS.covers_pct", f"{cc}.OPS.ticket_pct"]
            dev["supported"] = abs(covers - pct) <= 1 and abs(ticket) < 1
            dev["hypothesis"] = self.narrator.revenue(cname, cur, pct, covers, ticket, Decimal(cov_b["amount"]), Decimal(cov_a["amount"]), Decimal(tk_b["amount"]), Decimal(tk_a["amount"]), dev["supported"], ev)
            dev["evidence"] = ev
            return dev
        if cat in config.PURCHASE_CATEGORIES:
            dev["kind"] = "purchase"
            parsed = [(r, tools.parse_purchase(r["description"] or "")) for r in recs]
            parsed = [(r, p) for r, p in parsed if p]
            key = KEY[cat].lower()
            qty = sum((p["quantity"] for _, p in parsed), Decimal(0))
            amount = sum((abs(Decimal(r["amount"])) for r, _ in parsed), Decimal(0))
            if not parsed or qty == 0:
                dev["hypothesis"] = "Hipótesis no disponible: las descripciones de los registros no permiten leer precio unitario y cantidad."
                missing.append({"kind": "unexplained", "text": f"{cname} · {cat}: desviación relevante sin precio unitario/cantidad legibles; sin explicación posible.", "refs": []})
                return dev
            up = amount / qty
            supplier, unit = parsed[0][1]["supplier"], parsed[0][1]["unit"]
            self._fig(f"{k}.UP.ACT", f"{cname} · {cat} · precio unitario real", up, f"{cur}/{unit}", sources=[self._src(r) for r, _ in parsed], formula="importe / cantidad de los registros")
            self._fig(f"{k}.QTY.ACT", f"{cname} · {cat} · cantidad real", qty, unit, sources=[self._src(r) for r, _ in parsed], formula="suma de cantidades de las descripciones")
            ub, qb = ops.get((cc, f"{key}_unit_price_budget")), ops.get((cc, f"{key}_quantity_budget"))
            ev = [f"{k}.UP.ACT", f"{k}.QTY.ACT"]
            if not (ub and qb):
                dev["hypothesis"] = (f"Hipótesis parcial: según los registros, {supplier} cobró {tools.fmt(up, 4 if cur == 'USD' else 0)} {cur}/{unit}; no hay precio unitario ni cantidad "
                                     "presupuestados en operations.csv, por lo que la desviación no se puede atribuir a precio o a cantidad.")
                dev["evidence"] = ev
                missing.append({"kind": "missing_indicator", "text": f"{cname} · {cat}: faltan precio unitario/cantidad presupuestados; la desviación no se puede descomponer.", "refs": []})
                return dev
            pb, qbud = Decimal(ub["amount"]), Decimal(qb["amount"])
            self._fig(f"{k}.UP.BUD", f"{cname} · {cat} · precio unitario presupuestado", pb, f"{cur}/{unit}", sources=[self._src(ub)])
            self._fig(f"{k}.QTY.BUD", f"{cname} · {cat} · cantidad presupuestada", qbud, unit, sources=[self._src(qb)])
            price_eff, vol_eff = self.use("price_volume_effect", f"{cc}.{cat}", lambda: tools.price_volume_effect(up, qty, pb, qbud))
            self._fig(f"{k}.EFF.PRICE", f"{cname} · {cat} · efecto precio", price_eff, cur, components=[f"{k}.UP.ACT", f"{k}.QTY.ACT", f"{k}.UP.BUD"], formula="(precio real − precio presupuestado) × cantidad real")
            self._fig(f"{k}.EFF.QTY", f"{cname} · {cat} · efecto cantidad", vol_eff, cur, components=[f"{k}.QTY.ACT", f"{k}.QTY.BUD", f"{k}.UP.BUD"], formula="(cantidad real − cantidad presupuestada) × precio presupuestado")
            ev += [f"{k}.UP.BUD", f"{k}.QTY.BUD", f"{k}.EFF.PRICE", f"{k}.EFF.QTY"]
            up_pct, q_pct = tools.pct_change(pb, up), tools.pct_change(qbud, qty)
            dev["supported"] = True
            dev["hypothesis"] = self.narrator.purchase(cname, cat, supplier, cur, unit, pct, pb, up, up_pct, qbud, qty, q_pct, price_eff, vol_eff)
            dev["evidence"] = ev
            return dev
        # otra partida (p. ej. Marketing): solo las descripciones de los registros pueden apoyar una hipótesis
        reasons = [r for r in recs if _REASON_WORDS.search(r["description"] or "")]
        ev = [f"{k}.ACT", f"{k}.BUD"]
        if reasons:
            dev["supported"] = True
            dev["hypothesis"] = self.narrator.described(cname, cat, pct, [(r["entry_id"], r["description"]) for r in reasons])
        else:
            dev["hypothesis"] = self.narrator.unexplained(cname, cat, pct, len(recs))
            missing.append({"kind": "unexplained", "text": f"{cname} · {cat} ({tools.fmt_pct(pct)}): las descripciones de los {len(recs)} registros no indican el motivo; "
                            "con los datos disponibles no se puede explicar la desviación.", "refs": [r["entry_id"] for r in recs]})
        dev["evidence"] = ev
        return dev


class TemplateNarrator:
    """Redacción determinista de resúmenes e hipótesis a partir de cifras ya calculadas. Es el punto de extensión para un modelo de lenguaje:
    recibiría SOLO estos datos redactados (nunca registros crudos) y sus cifras seguirían viniendo de las herramientas."""

    def summary(self, report: dict) -> list[str]:
        c, countries = report["consolidated"], report["countries"]
        v = c["values"]
        res_var = Decimal(v["RES.ACT"]) - Decimal(v["RES.CMPBUD"])
        lines = [f"Cierre {report['period']}: resultado consolidado {tools.fmt(Decimal(v['RES.ACT']))} USD frente a {tools.fmt(Decimal(v['RES.CMPBUD']))} USD presupuestados"
                 f" ({tools.fmt(res_var)} USD){' — cifra PARCIAL: faltan datos' if not c['complete'] else ''}.",
                 f"Ingresos consolidados {tools.fmt(Decimal(v['INC.ACT']))} USD frente a {tools.fmt(Decimal(v['INC.BUD']))} USD presupuestados (tipo de cambio {report['fx']})."]
        rel = [d for d in report["deviations"]]
        lines.append(f"{len(rel)} desviación(es) relevante(s) (≥ {report['threshold_pct']} %): " + ("; ".join(f"{d['country_name']} · {d['label']} {tools.fmt_pct(Decimal(d['pct']))}" for d in rel) or "ninguna") + ".")
        miss = [m for m in report["missing"] if m["kind"] in ("missing_line", "missing_indicator", "no_budget")]
        dub = [m for m in report["missing"] if m["kind"] == "doubtful_record"]
        lines.append("Datos faltantes: " + ("; ".join(m["text"].split(":")[0] for m in miss) if miss else "ninguno") + (f". Registros dudosos excluidos: {len(dub)}." if dub else "."))
        lines.append("Estado: pendiente de revisión por Felipe Guerrero; no se distribuye hasta su aprobación.")
        return lines[:5]

    def revenue(self, country, cur, pct, covers, ticket, cov_b, cov_a, tk_b, tk_a, supported, ev) -> str:
        base = (f"cubiertos servidos {tools.fmt(cov_a, 0)} frente a {tools.fmt(cov_b, 0)} presupuestados ({tools.fmt_pct(covers)}) y ticket medio "
                f"{tools.fmt(tk_a)} {cur} frente a {tools.fmt(tk_b)} {cur} presupuestados ({tools.fmt_pct(ticket)})")
        if supported:
            return (f"Hipótesis: la desviación de ingresos de {country} ({tools.fmt_pct(pct)}) se debe a la variación del volumen de cubiertos, no al precio: {base}. "
                    f"La caída de cubiertos ({tools.fmt_pct(covers)}) equivale a la caída de ingresos y el ticket medio se mantuvo. "
                    "Los datos no indican por qué cayó la afluencia.")
        return (f"Hipótesis parcial: {base}. Estos indicadores no explican por completo la desviación de ingresos ({tools.fmt_pct(pct)}); "
                "faltan datos para atribuirla.")

    def purchase(self, country, cat, supplier, cur, unit, pct, pb, up, up_pct, qb, q, q_pct, price_eff, vol_eff) -> str:
        places = 4 if cur == "USD" else 0
        same_qty = abs(q_pct or 0) < 1
        txt = (f"Hipótesis: subida del precio unitario de {supplier}, de {tools.fmt(pb, places)} a {tools.fmt(up, places)} {cur}/{unit} ({tools.fmt_pct(up_pct)})"
               + (f", con la misma cantidad comprada ({tools.fmt(q, 0)} {unit}, presupuestada {tools.fmt(qb, 0)}). " if same_qty else
                  f", con una cantidad comprada de {tools.fmt(q, 0)} {unit} frente a {tools.fmt(qb, 0)} presupuestadas ({tools.fmt_pct(q_pct)}). ")
               + f"Efecto precio {tools.fmt(price_eff)} {cur} y efecto cantidad {tools.fmt(vol_eff)} {cur}: suman la desviación total de la partida ({tools.fmt_pct(pct)}). "
               "El precio unitario sale de las descripciones de los registros del libro.")
        return txt

    def described(self, country, cat, pct, items) -> str:
        return (f"Hipótesis: {country} · {cat} ({tools.fmt_pct(pct)}). Las descripciones de los registros apuntan a: "
                + "; ".join(f"{eid}: «{d}»" for eid, d in items) + ". Es una lectura de la descripción, no una confirmación.")

    def unexplained(self, country, cat, pct, n) -> str:
        return (f"Sin hipótesis sostenida por datos: {country} · {cat} ({tools.fmt_pct(pct)}). Las descripciones de los {n} registros no indican el motivo del gasto "
                "y no hay indicadores operativos que lo expliquen. Se requiere información del responsable de la partida; el sistema no inventa una causa.")


def content_hash(report: dict) -> str:
    """Huella de las CIFRAS y textos del informe (sin fechas ni versión): dos cierres del mismo periodo con los mismos datos dan la misma."""
    payload = {k: report[k] for k in ("period", "countries", "consolidated", "deviations", "missing", "summary", "figures")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
