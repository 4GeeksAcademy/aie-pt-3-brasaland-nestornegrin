from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth.dependencies import get_current_user
from .models import ALLOWED_TRANSITIONS, IncidentCreate, IncidentListItem, IncidentResponse, IncidentSummary, StatusUpdate
from .repository import IncidentRepository


def create_router(repository: IncidentRepository, prefix: str = "/api/incidents") -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["incidents"], dependencies=[Depends(get_current_user)])

    @router.post("", response_model=IncidentResponse, status_code=201)
    def create_incident(incident: IncidentCreate) -> IncidentResponse:
        return IncidentResponse.model_validate(repository.create(incident))

    @router.get("", response_model=list[IncidentListItem])
    def list_incidents(
        status: str | None = Query(default=None),
        origin: str | None = Query(default=None),
        branch: str | None = Query(default=None),
        category: str | None = Query(default=None),
    ) -> list[IncidentListItem]:
        # Listas vacías (sin datos o sin coincidencias) son una respuesta
        # válida, no un error: el frontend decide cómo comunicarlo.
        rows = repository.list(status=status, origin=origin, branch=branch, category=category)
        return [IncidentListItem.model_validate(row) for row in rows]

    @router.get("/summary", response_model=IncidentSummary)
    def incidents_summary() -> IncidentSummary:
        return IncidentSummary.model_validate(repository.summary())

    @router.get("/{incident_id}", response_model=IncidentResponse)
    def get_incident(incident_id: str) -> IncidentResponse:
        incident = repository.get(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="Incidencia no encontrada")
        return IncidentResponse.model_validate(incident)

    @router.patch("/{incident_id}/status", response_model=IncidentResponse)
    def update_incident_status(incident_id: str, update: StatusUpdate) -> IncidentResponse:
        current = repository.get(incident_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Incidencia no encontrada")

        if update.status == current.status:
            return IncidentResponse.model_validate(current)  # no-op idempotente, no es un error

        allowed = ALLOWED_TRANSITIONS.get(current.status, set())
        if update.status not in allowed:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"No se puede pasar de '{current.status.value}' a "
                    f"'{update.status.value}'. Transiciones permitidas desde "
                    f"'{current.status.value}': "
                    f"{', '.join(s.value for s in allowed) or 'ninguna (estado final)'}."
                ),
            )

        updated = repository.update_status(incident_id, update.status)
        assert updated is not None  # ya confirmamos que existe arriba
        return IncidentResponse.model_validate(updated)

    return router
