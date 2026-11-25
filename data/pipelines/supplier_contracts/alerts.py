"""Alertas (BRIEFING): subida de precio sobre umbral (carne de res > 3 %, resto > 8 %), vencimiento de contrato (90 y 30 días antes) y fecha
límite de preaviso (15 días antes). Van a Lucía Fernández (Compras) y a Felipe Guerrero. Ante una subida, el SUPERVISOR determina
automáticamente si el contrato la permite y su impacto. Idempotente: una misma alerta no se duplica."""
from __future__ import annotations

import json
from datetime import date

from . import config, tools
from .schemas import ContractRequest
from .store import Store, now
from .tools import fmt_es


class AlertService:
    def __init__(self, store: Store, supervisor):
        self.store, self.supervisor = store, supervisor

    def _add(self, key: str, kind: str, supplier_id: str, contract_id: str | None, stage: int | None, as_of: date, message: str, detail: dict) -> bool:
        if self.store.one("SELECT id FROM alerts WHERE key=?", (key,)):
            return False
        self.store.run("INSERT INTO alerts(key,kind,supplier_id,contract_id,stage,as_of,message,detail,recipients,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (key, kind, supplier_id, contract_id, stage, as_of.isoformat(), message, json.dumps(detail, default=str, ensure_ascii=False),
                        json.dumps(list(config.ALERT_RECIPIENTS)), now()))
        self.store.event("system", "system:alert-scan", "alert_created", f"alert:{key}", {"kind": kind, "supplier_id": supplier_id, "recipients": list(config.ALERT_RECIPIENTS)})
        return True

    def scan(self, as_of: date) -> list[dict]:
        for supplier in config.SUPPLIERS:
            self._price(supplier, as_of)
        for spec in config.CONTRACTS:
            self._contract(spec, as_of)
        return self.listing()

    def _price(self, supplier: config.Supplier, as_of: date) -> None:
        facts = self.supervisor.assess_increase(supplier.id, as_of)
        inc = facts["increase"]
        if inc is None or not inc.exceeds:
            return
        verdict = facts["verdict"]
        label = {"permitted": "PERMITIDA por el contrato", "not_permitted": "NO permitida por el contrato", "indeterminate": "contrato: indeterminado"}[verdict.verdict] if verdict else "sin contrato (compra por pedido)"
        usd = f" (≈ USD {fmt_es(inc.monthly_impact_usd)})" if inc.currency != "USD" and inc.monthly_impact_usd is not None else ""
        impact = f"; impacto ≈ {fmt_es(inc.monthly_impact)} {inc.currency}/mes{usd}" if inc.monthly_impact is not None else "; impacto no calculable (sin volumen de compra)"
        pending = f" ({len(verdict.pending_conditions)} condición(es) pendiente(s) de verificar)" if verdict and verdict.pending_conditions else ""
        places = 4 if inc.currency == "USD" else 0
        message = (f"{supplier.name} subió {fmt_es(inc.pct)}% ({fmt_es(inc.previous_price, places)} → {fmt_es(inc.current_price, places)} {inc.currency}/{inc.unit}), "
                   f"por encima del umbral del {inc.threshold_pct}%: {label}{pending}{impact}.")
        detail = {"increase": inc.model_dump(mode="json"), "verdict": verdict.model_dump(mode="json") if verdict else None,
                  "citations": [c.model_dump(mode="json") for c in facts["citations"]], "missing": facts["missing"]}
        self._add(f"price:{supplier.id}:{inc.month}", "price_increase", supplier.id, facts["contract_id"], None, as_of, message, detail)

    def _contract(self, spec: config.ContractSpec, as_of: date) -> None:
        resp = self.supervisor.consult_contract_for_alert(spec.supplier_id, as_of)
        name = config.SUPPLIER_BY_ID[spec.supplier_id].name
        for d in resp.deadlines:
            cite = d.citation.model_dump(mode="json")
            if d.kind == "expiry":
                stage = tools.expiry_stage(d.days_left)
                if stage is not None:
                    msg = (f"El contrato {spec.id} con {name} vence el {d.date} (en {d.days_left} días); alerta de {stage} días." if d.days_left >= 0
                           else f"El contrato {spec.id} con {name} venció el {d.date} (hace {-d.days_left} días).")
                    self._add(f"expiry:{spec.id}:{stage}", "contract_expiry", spec.supplier_id, spec.id, stage, as_of, msg, {"date": str(d.date), "days_left": d.days_left, "citation": cite})
            elif tools.notice_due(d.days_left):
                msg = (f"La fecha límite de preaviso del contrato {spec.id} con {name} es el {d.date} (en {d.days_left} días)." if d.days_left >= 0
                       else f"La fecha límite de preaviso del contrato {spec.id} con {name} venció el {d.date} (hace {-d.days_left} días).")
                self._add(f"notice:{spec.id}:{d.date}", "notice_deadline", spec.supplier_id, spec.id, config.NOTICE_ALERT_DAYS, as_of, msg,
                          {"date": str(d.date), "days_left": d.days_left, "citation": cite})

    def listing(self) -> list[dict]:
        rows = self.store.q("SELECT * FROM alerts ORDER BY id")
        for r in rows:
            r["detail"], r["recipients"] = json.loads(r["detail"]), json.loads(r["recipients"])
        return rows
