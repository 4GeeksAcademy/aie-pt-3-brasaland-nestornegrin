"""Fachada del flujo: ingesta/semilla, preguntas, brief, alertas, comunicaciones. Las rutas SOLO validan identidad y delegan aquí."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from . import config
from .alerts import AlertService
from .approvals import Approvals
from .generate import generate
from .ingest import ingest_all
from .store import Store
from .supervisor import Supervisor


class SupplierEngine:
    def __init__(self, store: Store | None = None, consult_limit: int = config.MAX_CONSULTS_PER_REQUEST):
        self.store = store or Store()
        self.store.seed_staff()                       # directorio: Felipe (Operaciones), Mariana (CEO), Lucía (Compras)
        self.supervisor = Supervisor(self.store, consult_limit)
        self.approvals = Approvals(self.store)
        self.alerts = AlertService(self.store, self.supervisor)

    @property
    def load_date(self) -> date | None:
        raw = self.store.meta("load_date")
        return date.fromisoformat(raw) if raw else None

    def seed(self, load_date: date, data_dir: Path | None = None) -> dict:
        data_dir = Path(data_dir or config.DEFAULT_DATA_DIR)
        generate(data_dir, load_date)
        return self.ingest(load_date, data_dir)

    def ingest(self, load_date: date, data_dir: Path) -> dict:
        result = ingest_all(self.store, data_dir, load_date)
        self.alerts.scan(load_date)
        return result

    def ask(self, question: str, as_of: date | None = None):
        return self.supervisor.ask(question, as_of or self.load_date or date.today())

    def brief(self, supplier_id: str, as_of: date | None = None, draft_message: bool = False):
        return self.supervisor.brief(supplier_id, as_of or self.load_date or date.today(), draft_message)

    def suppliers(self) -> list[dict]:
        out = []
        for s in config.SUPPLIERS:
            c = self.store.one("SELECT id, language FROM contracts WHERE supplier_id=?", (s.id,))
            out.append({"id": s.id, "name": s.name, "country": s.country, "category": s.category, "currency": s.currency,
                        "contract_id": c["id"] if c else None, "has_contract": c is not None})
        return out

    def contract_view(self, supplier_id: str, as_of: date | None = None):
        return self.supervisor.contract_view(supplier_id, as_of or self.load_date or date.today())

    def price_view(self, supplier_id: str, as_of: date | None = None):
        return self.supervisor.price_view(supplier_id, as_of or self.load_date or date.today())
