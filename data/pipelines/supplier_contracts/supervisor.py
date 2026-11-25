"""SUPERVISOR. Recibe la petición, decide a qué especialista consultar (precios, contratos o ambos), combina las respuestas en UNA y, a
petición, redacta el brief de renegociación o el borrador de comunicación. No calcula ni lee PDFs: solo habla con los especialistas a través
de los contratos de entrada/salida y compone el texto. Límite de consultas por petición (evita bucles). Todo mensaje queda registrado."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from . import config, tools
from .agents import BudgetExceeded, ConsultBudget, Toolbox
from .approvals import Approvals
from .contract_specialist import ContractSpecialist
from .price_specialist import PriceSpecialist
from .schemas import (Citation, ContractRequest, ContractResponse, Fact, PriceRequest, PriceResponse, SourceRef, SupervisorReply)
from .store import Store

_ALIASES = {"sunshine": "BR-S05", "carnes del valle": "BR-S01", "avicola antioquia": "BR-S02", "avicola": "BR-S02", "hortalizas": "BR-S03", "la sabana": "BR-S03",
            "frigorifico": "BR-S04", "andino": "BR-S04", "gulf coast": "BR-S06", "gulf poultry": "BR-S07", "brava": "BR-S08"}
_SRC = lambda refs: "; ".join(f"{r.file} fila {r.row}" for r in refs)          # noqa: E731


_fmt = tools.fmt_es


class Supervisor:
    agent_id = config.SUPERVISOR_ID

    def __init__(self, store: Store, limit: int = config.MAX_CONSULTS_PER_REQUEST):
        self.store, self.limit = store, limit
        self.price, self.contract, self.approvals = PriceSpecialist(store), ContractSpecialist(store), Approvals(store)

    # ------------------------------------------------------------------ consultas (única vía hacia los especialistas)
    def _consult_price(self, budget: ConsultBudget, rid: str, req: PriceRequest) -> PriceResponse:
        budget.take()
        self.store.message(rid, self.agent_id, config.PRICE_AGENT_ID, req.model_dump(mode="json"))
        resp = self.price.handle(req, rid)
        self.store.message(rid, config.PRICE_AGENT_ID, self.agent_id, resp.model_dump(mode="json"))
        self.store.event("agent", self.agent_id, "tool:consult_price_specialist", req.supplier_id, {"request": rid, "action": req.action})
        return resp

    def _consult_contract(self, budget: ConsultBudget, rid: str, req: ContractRequest) -> ContractResponse:
        budget.take()
        self.store.message(rid, self.agent_id, config.CONTRACT_AGENT_ID, req.model_dump(mode="json"))
        resp = self.contract.handle(req, rid)
        self.store.message(rid, config.CONTRACT_AGENT_ID, self.agent_id, resp.model_dump(mode="json"))
        self.store.event("agent", self.agent_id, "tool:consult_contract_specialist", req.supplier_id, {"request": rid, "action": req.action})
        return resp

    def _begin(self, kind: str, detail: dict, minimum: int = 0) -> tuple[str, ConsultBudget]:
        """`minimum`: las evaluaciones internas (alertas) siempre necesitan 2 consultas (precio + contrato); el tope sigue existiendo."""
        rid = uuid.uuid4().hex[:12]
        self.store.event("agent", self.agent_id, "request_received", kind, {"request": rid, **detail})
        return rid, ConsultBudget(max(self.limit, minimum))

    # ------------------------------------------------------------------ usos internos (alertas)
    def assess_increase(self, supplier_id: str, as_of: date) -> dict:
        """Ante una subida: ¿el contrato la permite y cuánto cuesta? Combina los dos especialistas (2 consultas)."""
        rid, budget = self._begin("assess_increase", {"supplier_id": supplier_id}, minimum=2)
        price = self._consult_price(budget, rid, PriceRequest(action="detect_increase", supplier_id=supplier_id, as_of=as_of))
        out = {"increase": price.increase, "verdict": None, "citations": [], "missing": list(price.missing), "contract_id": None}
        if price.increase is not None and price.increase.exceeds:
            c = self._consult_contract(budget, rid, ContractRequest(action="evaluate_increase", supplier_id=supplier_id, as_of=as_of, increase_pct=price.increase.pct))
            out.update(verdict=c.verdict, citations=c.citations, contract_id=c.contract_id)
            out["missing"] += c.missing
        return out

    def consult_contract_for_alert(self, supplier_id: str, as_of: date) -> ContractResponse:
        rid, budget = self._begin("contract_alerts", {"supplier_id": supplier_id}, minimum=1)
        return self._consult_contract(budget, rid, ContractRequest(action="deadlines", supplier_id=supplier_id, as_of=as_of))

    def contract_view(self, supplier_id: str, as_of: date) -> ContractResponse:
        rid, budget = self._begin("contract_view", {"supplier_id": supplier_id})
        return self._consult_contract(budget, rid, ContractRequest(action="terms", supplier_id=supplier_id, as_of=as_of))

    def price_view(self, supplier_id: str, as_of: date) -> PriceResponse:
        rid, budget = self._begin("price_view", {"supplier_id": supplier_id})
        return self._consult_price(budget, rid, PriceRequest(action="full_report", supplier_id=supplier_id, as_of=as_of))

    # ------------------------------------------------------------------ preguntas
    def detect_supplier(self, question: str) -> list[str]:
        t = config.normalize(question)
        found: list[str] = []
        for s in config.SUPPLIERS:
            if config.normalize(s.name) in t or s.id.lower() in t:
                found.append(s.id)
        for alias, sid in _ALIASES.items():
            if alias in t and sid not in found:
                found.append(sid)
        for spec in config.CONTRACTS:
            if spec.id.lower() in t and spec.supplier_id not in found:
                found.append(spec.supplier_id)
        return found

    @staticmethod
    def detect_intent(question: str) -> str:
        t = config.normalize(question)
        if "brief" in t or "renegoci" in t:
            return "brief"
        if ("cuando" in t and ("avis" in t or "notific" in t)) or "fecha limite" in t:
            return "notice_deadline"
        if "preaviso" in t:
            return "notice_period"
        if "permitid" in t or "permite" in t or ("subida" in t and "contrato" in t):
            return "permitted"
        if "cuanto" in t and ("cuesta" in t or "costo" in t or "impacto" in t):
            return "cost"
        if "alternativ" in t or "compar" in t:
            return "alternative"
        if "contrato" in t or "clausula" in t:
            return "summary"
        return "unknown"

    def ask(self, question: str, as_of: date) -> SupervisorReply:
        intent, suppliers = self.detect_intent(question), self.detect_supplier(question)
        rid, budget = self._begin("ask", {"intent": intent, "suppliers": suppliers})
        limit = budget.limit
        if intent == "unknown" or not suppliers:
            why = "No he entendido sobre qué proveedor preguntas." if not suppliers else "No he entendido qué necesitas saber."
            return SupervisorReply(intent=intent, answer=f"{why} Puedo responder sobre subidas de precio, qué permite el contrato, impacto mensual, alternativas, plazos de preaviso y preparar un brief de renegociación; nómbrame el proveedor.",
                                   consulted=[], consults_used=0, consults_limit=limit, missing=["Falta proveedor o intención reconocible."])
        sid = suppliers[0]
        name = config.SUPPLIER_BY_ID[sid].name
        reply = SupervisorReply(intent=intent, supplier_id=sid, answer="", consulted=[], consults_used=0, consults_limit=limit)
        try:
            if intent == "brief":
                return self._brief(sid, as_of, rid, budget, reply)
            handler = {"permitted": self._permitted, "cost": self._cost, "alternative": self._alternative, "notice_deadline": self._deadline,
                       "notice_period": self._notice, "summary": self._summary}[intent]
            handler(sid, name, as_of, rid, budget, reply, other=suppliers[1] if len(suppliers) > 1 else None)
        except BudgetExceeded as exc:
            reply.truncated = True
            reply.missing.append(f"Respuesta incompleta: {exc}.")
            reply.answer = (reply.answer + "\n\n" if reply.answer else "") + f"⚠️ Respuesta incompleta: {exc}."
        reply.consults_used = budget.used
        self.store.event("agent", self.agent_id, "tool:compose_answer", sid, {"request": rid, "intent": intent, "consults": budget.used})
        return reply

    # ---- piezas de composición
    @staticmethod
    def _cite_lines(cites: list[Citation]) -> list[str]:
        return [f"- {c.contract_id}, cláusula {c.clause}, p. {c.page} ({c.language.upper()}{', DUDOSA' if c.doubtful else ''}): «{c.quote}»" for c in cites]

    @staticmethod
    def _price_facts(inc) -> list[Fact]:
        return [Fact(key="previous_price", label="Precio mes anterior", value=str(inc.previous_price), unit=f"{inc.currency}/{inc.unit}", sources=[inc.sources[0]]),
                Fact(key="current_price", label="Precio del mes", value=str(inc.current_price), unit=f"{inc.currency}/{inc.unit}", sources=[inc.sources[1]])]

    def _permitted(self, sid, name, as_of, rid, budget, reply, **_):
        price = self._consult_price(budget, rid, PriceRequest(action="detect_increase", supplier_id=sid, as_of=as_of))
        reply.consulted.append(config.PRICE_AGENT_ID)
        reply.missing += price.missing
        inc = price.increase
        if inc is None:
            reply.answer = f"No puedo valorar la subida de {name}: " + (" ".join(price.missing) or "no hay datos.")
            return
        reply.facts += self._price_facts(inc)
        if inc.pct <= 0:
            reply.answer = f"{name} no ha subido: la variación del mes es {_fmt(inc.pct)}% ({_SRC(inc.sources)})."
            return
        c = self._consult_contract(budget, rid, ContractRequest(action="evaluate_increase", supplier_id=sid, as_of=as_of, increase_pct=inc.pct))
        reply.consulted.append(config.CONTRACT_AGENT_ID)
        reply.missing += c.missing
        head = (f"{name} subió {_fmt(inc.pct)}% ({_fmt(inc.previous_price, 4 if inc.currency == 'USD' else 0)} → {_fmt(inc.current_price, 4 if inc.currency == 'USD' else 0)} {inc.currency}/{inc.unit}; "
                f"{_SRC(inc.sources)}); " + ("supera" if inc.exceeds else "no supera") + f" el umbral del {inc.threshold_pct}%.")
        if c.status == "no_contract":
            reply.answer = head + f"\n\n{c.message} No hay cláusula que limite la subida."
            return
        v = c.verdict
        label = {"permitted": "SÍ, el contrato la permite", "not_permitted": "NO, el contrato no la permite", "indeterminate": "NO SE PUEDE AFIRMAR"}[v.verdict]
        lines = [head, "", f"**{label}.**"] + [f"- {r}" for r in v.reasons]
        if v.pending_conditions:
            lines += ["", "Condiciones pendientes (no verificables con los datos del sistema):"] + [f"- {p}" for p in v.pending_conditions]
        lines += ["", "Cláusulas:"] + self._cite_lines([x for x in c.citations if x.clause in {t.clause for t in c.terms if t.kind == "price_review"}])
        reply.answer, reply.citations = "\n".join(lines), c.citations

    def _cost(self, sid, name, as_of, rid, budget, reply, **_):
        price = self._consult_price(budget, rid, PriceRequest(action="detect_increase", supplier_id=sid, as_of=as_of))
        reply.consulted.append(config.PRICE_AGENT_ID)
        reply.missing += price.missing
        inc = price.increase
        if inc is None or inc.monthly_impact is None:
            reply.answer = f"No puedo calcular el coste mensual de {name}: " + (" ".join(price.missing) or "no hay datos.")
            return
        places = 4 if inc.currency == "USD" else 0
        reply.facts += self._price_facts(inc) + [Fact(key="monthly_impact", label="Coste extra al mes", value=str(inc.monthly_impact), unit=inc.currency, sources=inc.sources),
                                                 Fact(key="monthly_volume", label="Volumen mensual", value=str(inc.monthly_volume), unit=inc.unit, sources=[inc.sources[1]])]
        reply.answer = (f"La subida de {name} nos cuesta **{_fmt(inc.monthly_impact)} {inc.currency} al mes** (≈ USD {_fmt(inc.monthly_impact_usd)}; ≈ {_fmt(inc.annualized_impact)} {inc.currency} al año si se mantiene).\n\n"
                        f"Cálculo: ({_fmt(inc.current_price, places)} − {_fmt(inc.previous_price, places)}) {inc.currency}/{inc.unit} × {_fmt(Decimal(inc.monthly_volume), 0)} {inc.unit}/mes. "
                        f"Fuentes: {_SRC(inc.sources)}.")

    def _alternative(self, sid, name, as_of, rid, budget, reply, other=None, **_):
        price = self._consult_price(budget, rid, PriceRequest(action="peers", supplier_id=sid, as_of=as_of, compare_with=other))
        reply.consulted.append(config.PRICE_AGENT_ID)
        reply.missing += price.missing
        if not price.peers:
            reply.answer = f"No tengo alternativa comparable a {name}: " + (" ".join(price.missing) or "sin datos.")
            return
        inc, lines = price.increase, []
        for p in price.peers:
            sign = "más barato" if p.diff_abs < 0 else "más caro"
            line = (f"- **{p.name}**: {_fmt(p.price, 4 if p.currency == 'USD' else 0)} {p.currency}/{p.unit}, {_fmt(abs(p.diff_pct))}% {sign} que {name} ({p.source.file} fila {p.source.row})"
                    f"{' — COTIZACIÓN, sin compras ni contrato' if p.quote_only else ''}.")
            if p.monthly_saving is not None and not p.indicative:
                line += f" Al volumen actual, {'ahorraría' if p.monthly_saving > 0 else 'costaría de más'} {_fmt(abs(p.monthly_saving))} {p.currency} al mes."
            if p.note:
                line += f"\n  - ⚠️ {p.note}"
            lines.append(line)
        reply.answer = (f"Alternativas a {name} ({price.category}, {price.country}), comparadas con su precio actual de {_fmt(inc.current_price, 4 if inc.currency == 'USD' else 0)} {inc.currency}/{inc.unit}:\n\n" + "\n".join(lines))
        reply.facts += [Fact(key=f"peer:{p.supplier_id}", label=f"Precio {p.name}", value=str(p.price), unit=f"{p.currency}/{p.unit}", sources=[p.source]) for p in price.peers]

    def _deadline(self, sid, name, as_of, rid, budget, reply, **_):
        c = self._consult_contract(budget, rid, ContractRequest(action="deadlines", supplier_id=sid, as_of=as_of))
        reply.consulted.append(config.CONTRACT_AGENT_ID)
        reply.missing += c.missing
        if c.status == "no_contract":
            reply.answer = c.message
            return
        notice = next((d for d in c.deadlines if d.kind == "notice_deadline"), None)
        expiry = next((d for d in c.deadlines if d.kind == "expiry"), None)
        if notice is None:
            reply.answer = f"No puedo darte una fecha límite de preaviso para {name}: " + " ".join(m for m in c.missing)
            reply.citations = [d.citation for d in c.deadlines]
            return
        tn = next(t for t in c.terms if t.kind == "renewal_notice")
        what = ("el contrato se renueva AUTOMÁTICAMENTE por 12 meses salvo aviso" if tn.params["mode"] == "auto_renew_unless_notice" else "para no renovar hay que avisar")
        when = f"el **{notice.date}** (en {notice.days_left} días)" if notice.days_left >= 0 else f"el {notice.date} (**ya venció hace {-notice.days_left} días**)"
        reply.answer = (f"Hay que avisar a {name} como máximo {when}: {what}, {tn.params['notice_days']} días antes del vencimiento ({expiry.date}).\n\nCláusulas:\n"
                        + "\n".join(self._cite_lines([notice.citation, expiry.citation])))
        reply.citations = [notice.citation, expiry.citation]

    def _notice(self, sid, name, as_of, rid, budget, reply, **_):
        c = self._consult_contract(budget, rid, ContractRequest(action="notice", supplier_id=sid, as_of=as_of))
        reply.consulted.append(config.CONTRACT_AGENT_ID)
        reply.missing += c.missing
        if c.status == "no_contract":
            reply.answer = c.message
            return
        note = next((t for t in c.terms if t.kind == "renewal_notice"), None)
        exit_t = next((t for t in c.terms if t.kind == "exit"), None)
        if note is None:
            extra = (f" Lo único que fija es el preaviso de salida anticipada: {exit_t.params.get('notice_days')} días, sin penalización (cláusula {exit_t.clause}, p. {exit_t.page})." if exit_t and exit_t.params.get("notice_days") else "")
            reply.answer = f"**El contrato {c.contract_id} no especifica el preaviso** de renovación ni de no renovación: no incluye cláusula de preaviso, y no voy a suponer uno.{extra}"
            reply.citations = [self.contract.cite({"id": c.contract_id, "file": f"{c.contract_id}.pdf"}, exit_t)] if exit_t else []
            return
        reply.answer = f"El preaviso de {name} es de **{note.params['notice_days']} días** antes del vencimiento (cláusula {note.clause}, p. {note.page}).\n\n" + "\n".join(self._cite_lines([x for x in c.citations if x.clause == note.clause]))
        reply.citations = [x for x in c.citations if x.clause == note.clause]

    def _summary(self, sid, name, as_of, rid, budget, reply, **_):
        c = self._consult_contract(budget, rid, ContractRequest(action="terms", supplier_id=sid, as_of=as_of))
        reply.consulted.append(config.CONTRACT_AGENT_ID)
        reply.missing += c.missing
        if c.status == "no_contract":
            reply.answer = c.message
            return
        reply.answer = f"Contrato {c.contract_id} con {name}:\n\n" + "\n".join(self._cite_lines(c.citations))
        reply.citations = c.citations

    # ------------------------------------------------------------------ brief de renegociación
    def _brief(self, sid: str, as_of: date, rid: str, budget: ConsultBudget, reply: SupervisorReply, draft_message: bool = False, requested_by: str | None = None) -> SupervisorReply:
        name, supplier = config.SUPPLIER_BY_ID[sid].name, config.SUPPLIER_BY_ID[sid]
        price = contract = None
        try:
            price = self._consult_price(budget, rid, PriceRequest(action="full_report", supplier_id=sid, as_of=as_of))
            reply.consulted.append(config.PRICE_AGENT_ID)
            pct = price.increase.pct if price.increase is not None and price.increase.pct > 0 else None
            contract = self._consult_contract(budget, rid, ContractRequest(action="evaluate_increase", supplier_id=sid, as_of=as_of, increase_pct=pct))
            reply.consulted.append(config.CONTRACT_AGENT_ID)
        except BudgetExceeded as exc:
            reply.truncated = True
            reply.missing.append(f"Brief incompleto: {exc}.")
        reply.consults_used = budget.used
        brief = self.compose_brief(supplier, price, contract, as_of, reply.missing)
        reply.brief, reply.answer = brief, brief["markdown"]
        reply.citations = contract.citations if contract else []
        reply.missing = list(dict.fromkeys(reply.missing + brief["missing"]))
        if draft_message and not reply.truncated:
            comm = self.draft_communication(sid, brief, rid)
            brief["communication_id"] = comm["id"]
        self.store.event("agent", self.agent_id, "tool:compose_answer", sid, {"request": rid, "intent": "brief", "consults": budget.used})
        return reply

    def brief(self, supplier_id: str, as_of: date, draft_message: bool = False) -> SupervisorReply:
        rid, budget = self._begin("brief", {"supplier_id": supplier_id})
        reply = SupervisorReply(intent="brief", supplier_id=supplier_id, answer="", consulted=[], consults_used=0, consults_limit=budget.limit)
        return self._brief(supplier_id, as_of, rid, budget, reply, draft_message=draft_message)

    def compose_brief(self, supplier: config.Supplier, price: PriceResponse | None, contract: ContractResponse | None, as_of: date, extra_missing: list[str]) -> dict:
        missing = list(extra_missing)
        L = [f"# Brief de renegociación — {supplier.name} ({supplier.id})", f"_{supplier.category} · {supplier.country} · {supplier.currency} · datos a {as_of}_", ""]
        trace: list[dict] = []
        inc = price.increase if price else None
        places = 4 if supplier.currency == "USD" else 0
        if price is None:
            L += ["**No se pudo consultar al especialista de precios** (límite de consultas): el brief está incompleto."]
        else:
            missing += price.missing
            L += ["## 1. Qué ha pasado"]
            if inc is None:
                L += ["No hay variación calculable."]
            else:
                state = "supera" if inc.exceeds else "no supera"
                L += [f"{supplier.name} pasó de {_fmt(inc.previous_price, places)} a {_fmt(inc.current_price, places)} {inc.currency}/{inc.unit} (**{_fmt(inc.pct)}%** en {inc.month}); {state} el umbral del {inc.threshold_pct}% ({_SRC(inc.sources)})."]
                trace += [{"claim": f"Precio anterior {inc.previous_price}", "source": _SRC([inc.sources[0]])}, {"claim": f"Precio actual {inc.current_price}", "source": _SRC([inc.sources[1]])}]
            L += ["", "## 2. Histórico de 12 meses"]
            if price.history:
                L += ["| Mes | Precio | Fuente |", "|---|---|---|"] + [f"| {f.key.split(':')[1]} | {_fmt(Decimal(f.value), places)} {f.unit} | {_SRC(f.sources)} |" for f in price.history]
                lo, hi = min(Decimal(f.value) for f in price.history), max(Decimal(f.value) for f in price.history)
                L += ["", f"Mínimo {_fmt(lo, places)} · máximo {_fmt(hi, places)} {price.history[0].unit}."]
            L += ["", "## 3. Impacto económico"]
            if inc is not None and inc.monthly_impact is not None:
                L += [f"**{_fmt(inc.monthly_impact)} {inc.currency} al mes** (≈ USD {_fmt(inc.monthly_impact_usd)}) y {_fmt(inc.annualized_impact)} {inc.currency} al año: ({_fmt(inc.current_price, places)} − {_fmt(inc.previous_price, places)}) × {_fmt(Decimal(inc.monthly_volume), 0)} {inc.unit}/mes ({_SRC(inc.sources)})."]
                trace.append({"claim": f"Impacto mensual {inc.monthly_impact} {inc.currency}", "source": f"{_SRC(inc.sources)} (volumen {inc.monthly_volume})"})
            else:
                L += ["No se puede calcular: " + (" ".join(price.missing) or "sin datos de volumen.")]
            L += ["", f"## 4. Comparación con otros proveedores de {supplier.category} en {supplier.country}"]
            if price.peers:
                for p in price.peers:
                    L += [f"- {p.name}: {_fmt(p.price, 4 if p.currency == 'USD' else 0)} {p.currency}/{p.unit} ({'más barato' if p.diff_abs < 0 else 'más caro'} {_fmt(abs(p.diff_pct))}%; {p.source.file} fila {p.source.row})"
                          + (" — **cotización**, sin compras ni contrato" if p.quote_only else "")
                          + (f"; ahorro estimado al volumen actual: {_fmt(p.monthly_saving)} {p.currency}/mes" if p.monthly_saving is not None and p.monthly_saving > 0 else "")]
                    trace.append({"claim": f"Precio de {p.name} {p.price}", "source": f"{p.source.file} fila {p.source.row}"})
            else:
                L += ["No hay otro proveedor de la misma categoría y país con el que comparar."]
        L += ["", "## 5. Qué dice el contrato"]
        verdict_txt = "—"
        if contract is None:
            L += ["**No se pudo consultar al especialista de contratos** (límite de consultas): el brief está incompleto."]
        elif contract.status == "no_contract":
            missing += contract.missing
            L += [contract.message, "Sin contrato no hay cláusula de revisión ni de salida; solo rige el pedido."]
            verdict_txt = "sin contrato"
        else:
            missing += contract.missing
            if contract.verdict:
                v = contract.verdict
                verdict_txt = {"permitted": "permitida", "not_permitted": "no permitida", "indeterminate": "indeterminada"}[v.verdict]
                L += [{"permitida": "**La subida está PERMITIDA por el contrato.**", "no permitida": "**La subida NO está permitida por el contrato.**",
                       "indeterminada": "**No se puede afirmar si el contrato permite la subida.**"}[verdict_txt]] + [f"- {r}" for r in v.reasons]
                if v.allowed_max_pct is not None:
                    L += [f"- Margen contractual: hasta {_fmt(v.allowed_max_pct)}%; la subida es {_fmt(v.increase_pct)}% (margen restante: {_fmt(v.allowed_max_pct - v.increase_pct)} puntos)."]
                if v.pending_conditions:
                    L += ["", "Condiciones pendientes:"] + [f"- {p}" for p in v.pending_conditions]
            exit_t = next((t for t in contract.terms if t.kind == "exit"), None)
            L += ["", "**Salida del contrato:**"]
            if exit_t:
                pen = ("sin penalización" if exit_t.params.get("penalty") == "none"
                       else f"penalización de {exit_t.params['penalty_months']} meses de compra media" + (f" (≈ {_fmt(contract.exit_penalty_estimate)} {contract.annual_value_currency}, estimado como valor anual ÷ 12 × {exit_t.params['penalty_months']})" if contract.exit_penalty_estimate is not None else ""))
                days = f" con {exit_t.params['notice_days']} días de preaviso," if exit_t.params.get("notice_days") else ""
                L += [f"- Salida anticipada:{days} {pen} (cláusula {exit_t.clause}, p. {exit_t.page})."]
                trace.append({"claim": "Cláusula de salida", "source": f"{contract.contract_id} cláusula {exit_t.clause}, p. {exit_t.page}"})
            else:
                L += ["- El contrato no incluye cláusula de salida anticipada."]
            for d in contract.deadlines:
                L += [f"- {'Vencimiento' if d.kind == 'expiry' else 'Fecha límite de preaviso'}: {d.date} (en {d.days_left} días; cláusula {d.citation.clause}, p. {d.citation.page})."]
            L += ["", "Cláusulas citadas (idioma original):"] + self._cite_lines([c for c in contract.citations if c.clause in ({t.clause for t in contract.terms if t.kind in ('price_review', 'exit')})])
            trace += [{"claim": f"{c.contract_id}: {c.quote[:60]}…", "source": f"cláusula {c.clause}, p. {c.page}"} for c in contract.citations if c.clause in {t.clause for t in contract.terms if t.kind == "price_review"}]
        # --- recomendación (reglas fijas, sin cálculo)
        L += ["", "## 6. Recomendación"]
        if inc is None or not inc.exceeds:
            rec = "No hay una subida sobre el umbral que renegociar. Mantener la vigilancia."
        elif contract is not None and contract.status == "no_contract":
            cheaper = [p for p in (price.peers if price else []) if p.diff_abs < 0]
            rec = ("Sin contrato, la subida no está limitada: renegociar usando como palanca " + (f"la cotización de {cheaper[0].name}" if cheaper else "la posibilidad de cambiar de proveedor") + ".")
        elif verdict_txt == "no permitida":
            rec = "**Rechazar la subida y pedir su retirada**: el contrato no la ampara. "
            cheaper = [p for p in (price.peers if price else []) if p.diff_abs < 0]
            if cheaper:
                rec += f"Palanca: {cheaper[0].name} cotiza más barato. "
            if contract and any(d.kind == "notice_deadline" for d in contract.deadlines):
                nd = next(d for d in contract.deadlines if d.kind == "notice_deadline")
                rec += f"Ojo con la fecha límite de preaviso ({nd.date}, en {nd.days_left} días): si no se avisa a tiempo el contrato puede renovarse."
        elif verdict_txt == "permitida":
            rec = "La subida está dentro del margen contractual: no hay base para exigir su retirada; negociar solo si hay alternativa más barata o antes de la próxima revisión."
        else:
            rec = "No se puede afirmar si el contrato ampara la subida: revisar la cláusula a mano antes de comunicar nada."
        L += [rec]
        roles, value_usd = self.approvals.required_roles(supplier.id)
        names = {config.ROLE_OPS_DIRECTOR: "Felipe Guerrero", config.ROLE_CEO: "Mariana Restrepo"}
        L += ["", "## 7. Aprobación necesaria antes de contactar al proveedor",
              f"Aprueban: {' y '.join(names[r] for r in roles)}" + (f" (contrato de ≈ USD {_fmt(value_usd, 0)} al año > USD 200.000)" if len(roles) > 1 else " (cualquier comunicación a un proveedor)") + ". El sistema solo prepara el borrador; **nada sale sin su visto bueno.**"]
        missing = list(dict.fromkeys(missing))
        if missing:
            L += ["", "## Lo que falta (declarado, no estimado)"] + [f"- {m}" for m in missing]
        L += ["", "## Trazabilidad de cifras y cláusulas"] + [f"- {t['claim']} ← {t['source']}" for t in trace]
        return {"supplier_id": supplier.id, "as_of": as_of.isoformat(), "markdown": "\n".join(L), "missing": missing, "traceability": trace,
                "required_approvers": roles, "verdict": verdict_txt, "recommendation": rec}

    # ------------------------------------------------------------------ borrador de comunicación (nace pendiente de aprobación)
    def draft_communication(self, supplier_id: str, brief: dict, rid: str) -> dict:
        box = Toolbox(self.store, self.agent_id, rid)
        name = config.SUPPLIER_BY_ID[supplier_id].name
        body = (f"Estimados {name}:\n\nHemos revisado la variación de precios del último mes y quisiéramos conversar sobre ella.\n\n"
                f"{brief['recommendation'].replace('**', '')}\n\nQuedamos atentos para acordar una reunión.\n\nBrasaland — Operaciones")
        return box.use("draft_communication", supplier_id, lambda: self.approvals.draft(supplier_id, f"Revisión de precios — {name}", body, self.agent_id), {"request": rid})
