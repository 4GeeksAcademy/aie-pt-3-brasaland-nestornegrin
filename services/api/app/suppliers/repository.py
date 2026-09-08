from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from tinydb import Query, TinyDB

from .models import RateUpdate, StatusUpdate, Supplier, SupplierCreate
from .seed import seed_suppliers


class SupplierRepository:
    def __init__(self, database_path: Path) -> None:
        self._database = TinyDB(database_path, indent=2)
        self._lock = Lock()
        self._seed_if_empty()

    def _seed_if_empty(self) -> None:
        with self._lock:
            if len(self._database) == 0:
                self._database.insert_multiple([
                    {**supplier.model_dump(mode="json"), "updated_at": datetime.now(timezone.utc).isoformat()}
                    for supplier in seed_suppliers()
                ])

    def list(self, country: str | None = None, category: str | None = None) -> list[Supplier]:
        query = Query()
        predicates = []
        if country:
            predicates.append(query.country == country)
        if category:
            predicates.append(query.categories.any(category))
        with self._lock:
            rows = self._database.search(predicates[0] & predicates[1] if len(predicates) == 2 else predicates[0]) if predicates else self._database.all()
        return [Supplier.model_validate({**row, "id": row.doc_id}) for row in rows]

    def get(self, supplier_id: str) -> Supplier | None:
        with self._lock:
            row = self._database.get(doc_id=int(supplier_id)) if supplier_id.isdigit() else None
        return Supplier.model_validate({**row, "id": row.doc_id}) if row else None

    def create(self, supplier: SupplierCreate) -> Supplier:
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            document_id = self._database.insert({**supplier.model_dump(mode="json"), "updated_at": updated_at})
            row = self._database.get(doc_id=document_id)
        created = Supplier.model_validate({**row, "id": document_id})
        return created

    def update_rate(self, supplier_id: str, update: RateUpdate) -> Supplier | None:
        updated_at = datetime.now(timezone.utc)
        with self._lock:
            row = self._database.get(doc_id=int(supplier_id)) if supplier_id.isdigit() else None
            if row is None:
                return None
            self._database.update({"rate": update.rate, "updated_at": updated_at.isoformat()}, doc_ids=[row.doc_id])
            row["rate"] = update.rate
            row["updated_at"] = updated_at.isoformat()
        return Supplier.model_validate({**row, "id": row.doc_id})

    def update_status(self, supplier_id: str, update: StatusUpdate) -> Supplier | None:
        with self._lock:
            row = self._database.get(doc_id=int(supplier_id)) if supplier_id.isdigit() else None
            if row is None:
                return None
            self._database.update({"status": update.status.value}, doc_ids=[row.doc_id])
            row["status"] = update.status.value
        return Supplier.model_validate({**row, "id": row.doc_id})

    def delete(self, supplier_id: str) -> bool:
        with self._lock:
            return bool(self._database.remove(doc_ids=[int(supplier_id)])) if supplier_id.isdigit() else False