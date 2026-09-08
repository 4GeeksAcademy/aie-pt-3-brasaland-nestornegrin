from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from tinydb import Query, TinyDB

from .models import Incident, IncidentCategory, IncidentCreate, IncidentOrigin, IncidentStatus, Branch


class IncidentRepository:
    def __init__(self, database_path: Path) -> None:
        self._database = TinyDB(database_path, indent=2)
        self._lock = Lock()

    def create(self, incident: IncidentCreate) -> Incident:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            document_id = self._database.insert({
                **incident.model_dump(mode="json"),
                "status": IncidentStatus.OPEN.value,
                "created_at": now,
                "updated_at": now,
            })
            row = self._database.get(doc_id=document_id)
        return Incident.model_validate({**row, "id": document_id})

    def list(
        self,
        status: str | None = None,
        origin: str | None = None,
        branch: str | None = None,
        category: str | None = None,
    ) -> list[Incident]:
        query = Query()
        predicates = []
        if status:
            predicates.append(query.status == status)
        if origin:
            predicates.append(query.origin == origin)
        if branch:
            predicates.append(query.branch == branch)
        if category:
            predicates.append(query.category == category)

        with self._lock:
            if not predicates:
                rows = self._database.all()
            else:
                combined = predicates[0]
                for predicate in predicates[1:]:
                    combined = combined & predicate
                rows = self._database.search(combined)
        rows = sorted(rows, key=lambda row: row["created_at"], reverse=True)
        return [Incident.model_validate({**row, "id": row.doc_id}) for row in rows]

    def get(self, incident_id: str) -> Incident | None:
        with self._lock:
            row = self._database.get(doc_id=int(incident_id)) if incident_id.isdigit() else None
        return Incident.model_validate({**row, "id": row.doc_id}) if row else None

    def get_by_title(self, title: str) -> Incident | None:
        """Usado por el seed histórico para comprobar duplicados por título."""
        with self._lock:
            row = self._database.get(Query().title == title)
        return Incident.model_validate({**row, "id": row.doc_id}) if row else None

    def update_status(self, incident_id: str, new_status: IncidentStatus) -> Incident | None:
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            row = self._database.get(doc_id=int(incident_id)) if incident_id.isdigit() else None
            if row is None:
                return None
            self._database.update({"status": new_status.value, "updated_at": updated_at}, doc_ids=[row.doc_id])
            row["status"] = new_status.value
            row["updated_at"] = updated_at
        return Incident.model_validate({**row, "id": row.doc_id})

    def insert_historical(self, payload: dict, created_at_iso: str) -> Incident:
        """Inserta un registro del seed histórico con su timestamp original
        (en vez de 'ahora'), preservando cuándo ocurrió de verdad."""
        with self._lock:
            document_id = self._database.insert({
                **payload,
                "created_at": created_at_iso,
                "updated_at": created_at_iso,
            })
            row = self._database.get(doc_id=document_id)
        return Incident.model_validate({**row, "id": document_id})

    def summary(self) -> dict:
        with self._lock:
            rows = self._database.all()

        by_status = {status.value: 0 for status in IncidentStatus}
        by_category = {category.value: 0 for category in IncidentCategory}
        by_origin = {origin.value: 0 for origin in IncidentOrigin}
        by_branch = {branch.value: 0 for branch in Branch}

        for row in rows:
            by_status[row["status"]] = by_status.get(row["status"], 0) + 1
            by_category[row["category"]] = by_category.get(row["category"], 0) + 1
            by_origin[row["origin"]] = by_origin.get(row["origin"], 0) + 1
            by_branch[row["branch"]] = by_branch.get(row["branch"], 0) + 1

        return {
            "total": len(rows),
            "by_status": by_status,
            "by_category": by_category,
            "by_origin": by_origin,
            "by_branch": by_branch,
        }
