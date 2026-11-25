"""Especialista de CONTRATOS. Entrada: ContractRequest. Salida: ContractResponse. Solo lee términos ya extraídos (con cláusula y página) y
llama a las herramientas deterministas de fechas e importes; no conoce los precios: la subida a evaluar se la entrega el supervisor.
Si el contrato no dice algo, lo declara en `missing`: nunca lo supone."""
from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from . import config, tools
from .agents import Toolbox
from .schemas import Citation, ContractRequest, ContractResponse, Deadline, IncreaseVerdict, Term
from .store import Store


class ContractSpecialist:
    agent_id = config.CONTRACT_AGENT_ID

    def __init__(self, store: Store):
        self.store = store

    # ---- lectura
    def _contract(self, supplier_id: str) -> dict | None:
        return self.store.one("SELECT * FROM contracts WHERE supplier_id=?", (supplier_id,))

    def _terms(self, contract_id: str) -> list[Term]:
        rows = self.store.q("SELECT * FROM terms WHERE contract_id=? ORDER BY CAST(clause AS INTEGER)", (contract_id,))
        return [Term(kind=r["kind"], clause=r["clause"], page=r["page"], quote=r["quote"], language=r["language"], confidence=r["confidence"],
                     doubtful=bool(r["doubtful"]), params=json.loads(r["params"])) for r in rows]

    @staticmethod
    def cite(contract: dict, term: Term) -> Citation:
        return Citation(contract_id=contract["id"], file=contract["file"], clause=term.clause, page=term.page, quote=term.quote,
                        language=term.language, confidence=term.confidence, doubtful=term.doubtful)

    @staticmethod
    def _first(terms: list[Term], kind: str) -> Term | None:
        return next((t for t in terms if t.kind == kind), None)

    # ---- entrada principal
    def handle(self, req: ContractRequest, request_id: str) -> ContractResponse:
        box = Toolbox(self.store, self.agent_id, request_id)
        supplier = config.SUPPLIER_BY_ID.get(req.supplier_id)
        if supplier is None:
            return ContractResponse(status="not_found", supplier_id=req.supplier_id, message=f"No existe el proveedor {req.supplier_id}.")
        contract = box.use("read_contract_terms", supplier.id, lambda: self._contract(supplier.id), {"action": req.action})
        if contract is None:
            return ContractResponse(status="no_contract", supplier_id=supplier.id, supplier_name=supplier.name,
                                    message=f"No hay contrato con {supplier.name}: se compra por pedido, así que no existe ninguna cláusula que consultar.",
                                    missing=[f"No hay contrato con {supplier.name} (compra por pedido)."])
        terms = box.use("read_contract_terms", contract["id"], lambda: self._terms(contract["id"]))
        resp = ContractResponse(status="ok", supplier_id=supplier.id, supplier_name=supplier.name, contract_id=contract["id"],
                                language=contract["language"], terms=terms)
        value = self._first(terms, "annual_value")
        if value is not None and not value.doubtful:
            amount, currency = Decimal(value.params["amount"]), value.params["currency"]
            resp.annual_value, resp.annual_value_currency = amount, currency
            resp.annual_value_usd = box.use("convert_currency", contract["id"], lambda: tools.to_usd(amount, currency))
        else:
            resp.missing.append("No se pudo leer con confianza el valor anual del contrato.")
        exit_term = self._first(terms, "exit")
        if exit_term and exit_term.params.get("penalty") == "months_of_average_purchases" and resp.annual_value is not None:
            resp.exit_penalty_estimate = tools.q2(resp.annual_value / 12 * exit_term.params["penalty_months"])
        for t in terms:
            if t.doubtful:
                resp.missing.append(f"Cláusula {t.clause} (p. {t.page}) de {contract['id']}: extracción de baja confianza ({t.confidence:.2f}); revisar a mano.")

        if req.action == "evaluate_increase" and req.increase_pct is not None:
            resp.verdict = box.use("check_price_increase", contract["id"], lambda: self._verdict(supplier.id, contract, terms, req.increase_pct, resp),
                                   {"increase_pct": str(req.increase_pct)})
        if req.action in ("deadlines", "notice", "evaluate_increase"):
            resp.deadlines = box.use("compute_deadlines", contract["id"], lambda: self._deadlines(contract, terms, req.as_of, resp))
        if req.action == "notice":
            note = self._first(terms, "renewal_notice")
            if note is None:
                resp.missing.append(f"El contrato {contract['id']} no especifica preaviso de renovación ni de no renovación (no incluye cláusula de preaviso).")
        resp.citations = self._citations(contract, terms, req.action, resp)
        return resp

    def _citations(self, contract: dict, terms: list[Term], action: str, resp: ContractResponse) -> list[Citation]:
        wanted = {"terms": {"expiry", "renewal_notice", "price_review", "exit", "annual_value"}, "notice": {"renewal_notice", "expiry"},
                  "deadlines": {"expiry", "renewal_notice"}, "evaluate_increase": {"price_review", "exit", "expiry", "renewal_notice"}}[action]
        out = [self.cite(contract, t) for t in terms if t.kind in wanted]
        if resp.annual_value is not None and action in ("terms", "evaluate_increase"):
            v = self._first(terms, "annual_value")
            if v and all(c.clause != v.clause for c in out):
                out.append(self.cite(contract, v))
        return out

    # ---- herramienta: fechas límite
    def _deadlines(self, contract: dict, terms: list[Term], as_of: date, resp: ContractResponse) -> list[Deadline]:
        out: list[Deadline] = []
        expiry = self._first(terms, "expiry")
        if expiry is None or expiry.doubtful or "date" not in expiry.params:
            resp.missing.append(f"No consta con confianza la fecha de vencimiento de {contract['id']}.")
            return out
        when = date.fromisoformat(expiry.params["date"])
        out.append(Deadline(kind="expiry", date=when, days_left=tools.days_between(as_of, when), citation=self.cite(contract, expiry)))
        notice = self._first(terms, "renewal_notice")
        if notice is None:
            resp.missing.append(f"El contrato {contract['id']} no especifica preaviso de renovación ni de no renovación: no hay fecha límite de preaviso que calcular.")
        elif notice.doubtful or "notice_days" not in notice.params:
            resp.missing.append(f"No se pudo leer con confianza el plazo de preaviso de la cláusula {notice.clause} de {contract['id']}.")
        else:
            limit = tools.notice_deadline(when, notice.params["notice_days"])
            out.append(Deadline(kind="notice_deadline", date=limit, days_left=tools.days_between(as_of, limit), citation=self.cite(contract, notice)))
        return out

    # ---- herramienta: ¿permite el contrato esta subida?
    def _verdict(self, supplier_id: str, contract: dict, terms: list[Term], pct: Decimal, resp: ContractResponse) -> IncreaseVerdict:
        review = self._first(terms, "price_review")
        if review is None:
            resp.missing.append(f"El contrato {contract['id']} no incluye cláusula de revisión de precios.")
            return IncreaseVerdict(verdict="indeterminate", increase_pct=pct, reasons=["El contrato no tiene cláusula de revisión de precios: no se puede afirmar nada."])
        ref = f"cláusula {review.clause}, p. {review.page}"
        if review.doubtful or "type" not in review.params:
            return IncreaseVerdict(verdict="indeterminate", increase_pct=pct, reasons=[f"La cláusula {review.clause} (p. {review.page}) se leyó con baja confianza: revisarla a mano antes de decidir."])
        kind, params = review.params["type"], review.params
        notice_days = params.get("written_notice_days")
        has_notice = bool(self.store.notices(supplier_id, "price_increase_notice"))
        pending: list[str] = []
        if kind == "cpi_plus":
            cap = tools.cpi_cap(Decimal(params["points"]))
            if params.get("frequency") == "semiannual":
                pending.append("No consta la fecha de la última revisión semestral: no se puede comprobar que toque revisar.")
            if notice_days and not has_notice:
                pending.append(f"Falta el preaviso escrito de {notice_days} días exigido por la {ref}: no hay registro de que se haya enviado.")
            if pct <= cap:
                return IncreaseVerdict(verdict="permitted", increase_pct=pct, allowed_max_pct=cap, pending_conditions=pending,
                                       reasons=[f"La subida del {pct}% no supera el tope de la cláusula: IPC anual de Colombia {config.COLOMBIA_CPI}% + {params['points']} punto = {cap}% ({ref})."])
            return IncreaseVerdict(verdict="not_permitted", increase_pct=pct, allowed_max_pct=cap, pending_conditions=pending,
                                   reasons=[f"La subida del {pct}% supera el tope de la cláusula: IPC {config.COLOMBIA_CPI}% + {params['points']} punto = {cap}% ({ref})."])
        if kind == "annual_cap":
            cap = Decimal(params["cap_pct"])
            if pct <= cap:
                return IncreaseVerdict(verdict="permitted", increase_pct=pct, allowed_max_pct=cap, reasons=[f"La subida del {pct}% está dentro del máximo anual del {cap}% ({ref})."])
            return IncreaseVerdict(verdict="not_permitted", increase_pct=pct, allowed_max_pct=cap, reasons=[f"La subida del {pct}% excede el máximo anual del {cap}% ({ref})."])
        if kind == "fixed_unless_index":
            threshold = Decimal(params["index_threshold_pct"])
            reasons = [f"Según la {ref} el precio es FIJO durante la vigencia; solo puede subir si el índice de referencia de carne de res sube más de un {threshold}% en el trimestre, con preaviso escrito de {notice_days} días."]
            evidence = self.store.notices(supplier_id, "index_evidence")
            index_ok = bool(evidence) and Decimal(evidence[-1]["ref"]) > threshold
            if not evidence:
                reasons.append("No hay registro de la prueba del índice de referencia (el sistema no la tiene; no se estima).")
            elif not index_ok:
                reasons.append(f"El índice registrado ({evidence[-1]['ref']}%) no supera el {threshold}%.")
            if not has_notice:
                reasons.append("No hay registro del preaviso escrito.")
            if index_ok and has_notice:
                return IncreaseVerdict(verdict="permitted", increase_pct=pct, reasons=reasons[:1] + ["Constan la prueba del índice y el preaviso escrito."],
                                       pending_conditions=["La cláusula no fija un tope de la subida: revisar a mano que sea proporcionada."])
            return IncreaseVerdict(verdict="not_permitted", increase_pct=pct, reasons=reasons)
        if kind == "free_list":
            return IncreaseVerdict(verdict="permitted", increase_pct=pct, reasons=[f"El precio es libre según la lista trimestral del proveedor ({ref}): el contrato no limita la subida."])
        return IncreaseVerdict(verdict="indeterminate", increase_pct=pct, reasons=["Tipo de cláusula de revisión no reconocido."])
