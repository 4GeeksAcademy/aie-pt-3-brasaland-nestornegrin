"""Informe de cierre en Markdown con la estructura EXACTA del briefing (6 secciones) a partir del JSON del agente.
Solo formatea: no calcula nada (las cifras vienen del agente y sus herramientas deterministas)."""
from __future__ import annotations

from decimal import Decimal

from . import config
from .tools import fmt, fmt_pct

SECTIONS = ("Resumen ejecutivo", "Resultado consolidado en USD", "Resultado por país (moneda local)", "Desviaciones relevantes",
            "Datos faltantes o dudosos", "Anexo de trazabilidad")


def _d(x): return None if x is None else Decimal(x)
def _f(x, p=2): return "—" if x is None else fmt(Decimal(x), p)


def response_to_comments(report: dict, comments: list[str], by_line_records: dict[tuple, list[dict]]) -> list[dict]:
    """Respuesta determinista a los comentarios del revisor: si menciona una partida o un país, se amplía su detalle (registros de origen);
    lo que no se puede atender automáticamente se DECLARA, no se ignora."""
    from .config import norm
    out = []
    for text in comments:
        t = norm(text)
        hits = []
        for cc, c in report["countries"].items():
            for line in c["lines"]:
                if norm(line["category"]) in t and (norm(c["name"]) in t or norm(cc) in t.split() or not any(norm(n) in t for _, (n, _) in config.COUNTRIES.items())):
                    hits.append((cc, line))
        if hits:
            detail = []
            for cc, line in hits:
                recs = by_line_records.get((cc, line["category"]), [])
                detail.append({"country": report["countries"][cc]["name"], "label": line["label"], "currency": line["currency"], "budget": line["budget"],
                               "actual": line["actual"], "records": [{"entry_id": r["entry_id"], "date": r["date"], "amount": r["amount"], "description": r["description"]} for r in recs]})
            out.append({"comment": text, "handled": True, "detail": detail, "note": "Se amplía el detalle de la(s) partida(s) mencionada(s), con sus registros de origen."})
        else:
            out.append({"comment": text, "handled": False, "detail": [],
                        "note": "Este comentario no se puede atender automáticamente (no menciona una partida o país reconocible); queda registrado para que lo resuelva una persona."})
    return out


def sources_text(f: dict) -> str:
    ids = [s["entry_id"] for s in f["sources"] if s.get("entry_id")]
    other = [f"{s['file']}:{s['row']}" for s in f["sources"] if not s.get("entry_id")]
    return ", ".join(ids + other) or "—"


def render(report: dict, version: int = 1, status: str = "pending_review") -> str:
    c, fig = report["consolidated"], report["figures"]
    L: list[str] = [f"# Cierre financiero {report['period']} — Brasaland", "",
                    f"_Versión {version} · estado: {status} · idioma: {report['language']} · tipo de cambio de consolidación: **{report['fx']}** · umbral de desviación relevante: ≥ {report['threshold_pct']} %_", ""]
    if report.get("revision"):
        L += ["> **Versión generada tras el rechazo de la anterior.** Respuesta a los comentarios de la revisión:", ">"]
        for r in report["revision"]:
            L.append(f"> - «{r['comment']}» → {'ATENDIDO' if r['handled'] else 'NO ATENDIDO AUTOMÁTICAMENTE'}: {r['note']}")
        L.append("")
        for r in report["revision"]:
            for dt in r["detail"]:
                L += [f"**Detalle ampliado — {dt['country']} · {dt['label']}** (presupuesto {_f(dt['budget'])} {dt['currency']}, real {_f(dt['actual'])} {dt['currency']}):", "",
                      "| entry_id | Fecha | Importe | Descripción |", "|---|---|---:|---|"]
                L += [f"| {x['entry_id']} | {x['date']} | {_f(x['amount'])} | {x['description']} |" for x in dt["records"]] + [""]
    L += ["## 1. Resumen ejecutivo", ""] + [f"- {s}" for s in report["summary"]] + [""]
    L += ["## 2. Resultado consolidado en USD", "", f"Cada país se convierte a USD con **{report['fx']}** antes de sumar; nunca se suman monedas distintas sin convertir.", "",
          "| Concepto | Real (USD) | Presupuesto (USD) | Presupuesto comparable (USD) | Desviación vs comparable (USD) |", "|---|---:|---:|---:|---:|"]
    for r in c["rows"]:
        L.append(f"| {r['label']} | {_f(r['act'])} | {_f(r['bud'])} | {_f(r['cmp_bud'])} | {_f(Decimal(r['act']) - Decimal(r['cmp_bud']))} |")
    if c.get("note"):
        L += ["", f"**Atención:** {c['note']}"]
    L.append("")
    L += ["## 3. Resultado por país (moneda local)", ""]
    for cc, ctry in report["countries"].items():
        cur = ctry["currency"]
        L += [f"### {ctry['name']} ({cur})", "", f"| Partida | Presupuesto ({cur}) | Real ({cur}) | Desviación ({cur}) | Desviación % | Relevante |", "|---|---:|---:|---:|---:|:---:|"]
        for l in ctry["lines"]:
            if l["actual"] is None:
                L.append(f"| {l['label']} | {_f(l['budget'])} | **SIN REGISTROS** | — | — | dato faltante |")
            else:
                L.append(f"| {l['label']}{' ⚠ parcial' if l['status'] == 'partial' else ''} | {_f(l['budget'])} | {_f(l['actual'])} | {_f(l['var_abs'])} | {fmt_pct(_d(l['pct'])) if l['pct'] else '—'} | {'**SÍ**' if l['relevant'] else 'no'} |")
        t = ctry["totals"]
        if t.get("income_act") is not None and t.get("result_act") is not None:
            L += ["", f"Ingresos {_f(t['income_act'])} {cur} · gastos reales {_f(t['expenses_act'])} {cur}{'' if t['complete'] else ' (PARCIALES)'} · resultado {_f(t['result_act'])} {cur}"
                  f" (presupuesto comparable {_f(t['result_cmp_bud'])} {cur})."]
        if t.get("note"):
            L.append(f"_{t['note']}_")
        L.append("")
    L += ["## 4. Desviaciones relevantes", ""]
    if not report["deviations"]:
        L += ["Ninguna partida supera el umbral.", ""]
    for i, d in enumerate(report["deviations"], 1):
        sign = "a favor" if d["favorable"] else "en contra"
        figs = [fig[x] for x in d["figs"] if x] + [fig[x] for x in d["evidence"] if x in fig]
        L += [f"### 4.{i} {d['country_name']} · {d['label']}: {fmt_pct(_d(d['pct']))} ({sign})", "",
              f"Desviación: {_f(d['var_abs'])} {d['currency']}. {d['hypothesis']}", "",
              "Cifras que la sostienen: " + "; ".join(f"`{f['id']}` = {_f(f['value'], 4) if f['unit'] != '%' else fmt_pct(Decimal(f['value']))} {f['unit']}".strip() for f in figs), ""]
    L += ["## 5. Datos faltantes o dudosos", ""]
    L += [f"- **{m['kind']}** — {m['text']}" + (f" (registros: {', '.join(m['refs'])})" if m["refs"] else "") for m in report["missing"]] or ["Ninguno."]
    L.append("")
    L += ["## 6. Anexo de trazabilidad", "", "Para cada cifra: su fórmula y los `entry_id` (o fila de `budget.csv`/`operations.csv`) que la producen.", "",
          "| Cifra | Valor | Unidad | Estado | Fórmula | Origen |", "|---|---:|---|---|---|---|"]
    for f in sorted(fig.values(), key=lambda x: x["id"]):
        v = "—" if f["value"] is None else fmt(Decimal(f["value"]), 4 if f["unit"] not in ("COP", "USD", "%", "") else 2)
        L.append(f"| `{f['id']}` | {v} | {f['unit']} | {f['status']} | {f['formula'] or 'dato de origen'} | {sources_text(f)} |")
    L.append("")
    return "\n".join(L)
