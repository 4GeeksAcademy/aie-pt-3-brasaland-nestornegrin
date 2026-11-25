"""Especialista de PRECIOS. Entrada: PriceRequest. Salida: PriceResponse. Solo lee precios y llama a las herramientas deterministas;
no conoce los contratos. Cada cifra devuelve las filas del CSV de las que sale."""
from __future__ import annotations

from decimal import Decimal

from . import config, tools
from .agents import Toolbox
from .schemas import Fact, IncreaseInfo, PeerQuote, PriceRequest, PriceResponse, SourceRef
from .store import Store


class PriceSpecialist:
    agent_id = config.PRICE_AGENT_ID

    def __init__(self, store: Store):
        self.store = store

    # ---- herramienta: leer precios
    def _rows(self, supplier_id: str) -> list[dict]:
        return self.store.q("SELECT * FROM prices WHERE supplier_id=? ORDER BY month", (supplier_id,))

    @staticmethod
    def _src(row: dict) -> SourceRef:
        return SourceRef(file=row["source_file"], row=row["source_row"])

    def handle(self, req: PriceRequest, request_id: str) -> PriceResponse:
        box = Toolbox(self.store, self.agent_id, request_id)
        supplier = config.SUPPLIER_BY_ID.get(req.supplier_id)
        if supplier is None:
            return PriceResponse(status="not_found", supplier_id=req.supplier_id, missing=[f"No existe el proveedor {req.supplier_id}."])
        base = dict(supplier_id=supplier.id, supplier_name=supplier.name, category=supplier.category, country=supplier.country)
        rows = box.use("read_prices", supplier.id, lambda: self._rows(supplier.id), {"action": req.action})
        if not rows:
            return PriceResponse(status="no_data", **base, missing=[f"No hay histórico de precios de {supplier.name}."])
        resp = PriceResponse(status="ok", **base)
        if req.action in ("history", "full_report"):
            resp.history = [Fact(key=f"price:{r['month']}", label=f"Precio {r['month']}", value=r["unit_price"], unit=f"{r['currency']}/{r['unit']}",
                                 sources=[self._src(r)]) for r in rows]
        if req.action in ("detect_increase", "full_report", "peers"):
            resp.increase = box.use("detect_increase", supplier.id, lambda: self._increase(rows, supplier), {"month": rows[-1]["month"]}) \
                if len(rows) >= 2 else None
            if resp.increase is None:
                resp.missing.append("Hay menos de dos meses de histórico: no se puede calcular una variación.")
            elif resp.increase.monthly_volume:
                resp.increase.monthly_impact = box.use("compute_impact", supplier.id, lambda: tools.monthly_impact(
                    resp.increase.previous_price, resp.increase.current_price, resp.increase.monthly_volume))
                resp.increase.monthly_impact_usd = box.use("convert_currency", supplier.id, lambda: tools.to_usd(resp.increase.monthly_impact, supplier.currency))
                resp.increase.annualized_impact = tools.q2(resp.increase.monthly_impact * 12)
            else:
                resp.missing.append(f"{supplier.name} no tiene volumen de compra (solo cotización): no se puede calcular el impacto económico.")
        if req.action in ("peers", "full_report"):
            self._peers(box, req, resp, rows, supplier)
        return resp

    def _increase(self, rows: list[dict], supplier: config.Supplier) -> IncreaseInfo:
        prev, cur = rows[-2], rows[-1]
        previous, current = Decimal(prev["unit_price"]), Decimal(cur["unit_price"])
        pct = tools.pct_change(previous, current)
        return IncreaseInfo(supplier_id=supplier.id, product=cur["product"], unit=cur["unit"], currency=cur["currency"], month=cur["month"],
                            previous_price=previous, current_price=current, pct=pct, threshold_pct=tools.threshold_for(supplier.category),
                            exceeds=tools.exceeds_threshold(pct, supplier.category), monthly_volume=cur["monthly_volume"],
                            sources=[self._src(prev), self._src(cur)])

    def _peers(self, box: Toolbox, req: PriceRequest, resp: PriceResponse, rows: list[dict], supplier: config.Supplier) -> None:
        own = rows[-1]
        own_price, volume = Decimal(own["unit_price"]), own["monthly_volume"]
        same = [s for s in config.SUPPLIERS if s.id != supplier.id and s.category == supplier.category and s.country == supplier.country]
        if not same:
            resp.missing.append(f"No hay otro proveedor de {supplier.category} en {supplier.country} con el que comparar (las comparativas son del mismo país y categoría).")
        for peer in same:
            prow = box.use("read_prices", peer.id, lambda p=peer: self._rows(p.id))
            if not prow:
                resp.missing.append(f"No hay precios de {peer.name}.")
                continue
            last = prow[-1]
            if last["unit"] != own["unit"]:
                resp.missing.append(f"{peer.name} cotiza en {last['unit']} y {supplier.name} en {own['unit']}: unidades no comparables sin conversión.")
                continue
            price = Decimal(last["unit_price"])
            diff, pct, saving = box.use("compare_peers", peer.id, lambda: tools.peer_gap(own_price, price, volume))
            resp.peers.append(PeerQuote(supplier_id=peer.id, name=peer.name, price=price, unit=last["unit"], currency=last["currency"],
                                        quote_only=last["monthly_volume"] == 0, diff_abs=diff, diff_pct=pct,
                                        monthly_saving=saving if volume else None,
                                        note="Es una cotización (sin compras ni contrato): no hay histórico de entregas." if last["monthly_volume"] == 0 else "",
                                        source=self._src(last)))
        if req.compare_with:
            other = config.SUPPLIER_BY_ID.get(req.compare_with)
            if other is None:
                resp.missing.append(f"No existe el proveedor {req.compare_with}.")
            elif other.country == supplier.country:
                resp.notes.append("Ese proveedor es del mismo país: ya aparece en la comparativa normal.")
            elif other.category != supplier.category:
                resp.missing.append(f"{other.name} es de otra categoría ({other.category}): no se compara.")
            else:
                orow = box.use("read_prices", other.id, lambda: self._rows(other.id))[-1]
                mine = box.use("convert_currency", supplier.id, lambda: tools.price_per_kg_usd(own_price, own["unit"], own["currency"]))
                theirs = tools.price_per_kg_usd(Decimal(orow["unit_price"]), orow["unit"], orow["currency"])
                diff, pct, _ = tools.peer_gap(mine, theirs, 0)
                resp.peers.append(PeerQuote(supplier_id=other.id, name=other.name, price=theirs, unit="kg", currency="USD", quote_only=orow["monthly_volume"] == 0,
                                            diff_abs=diff, diff_pct=pct, indicative=True, source=self._src(orow),
                                            note=f"Mercados distintos ({supplier.country} vs {other.country}): comparación SOLO ORIENTATIVA, convertida a USD/kg al tipo de "
                                                 f"cambio de referencia (1 USD = {config.FX_COP_PER_USD:,.0f} COP).".replace(",", ".")))
                resp.notes.append("Comparación entre mercados distintos: solo orientativa.")
