from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..auth.dependencies import get_current_user
from ..cache import TTLCache
from .models import ALLOWED_TRANSITIONS, IncidentCreate, IncidentListItem, IncidentResponse, IncidentSummary, StatusUpdate
from .repository import IncidentRepository


# Caché de lectura de incidencias (decisiones y números en CACHING_REPORT.md).
# 30 s: las incidencias cambian de estado varias veces al día, no por segundo,
# y toda escritura hecha a través de esta API invalida la caché al instante;
# el TTL solo acota la antigüedad de cambios hechos fuera de este proceso
# (otro worker, un script de seed). Los datos son los mismos para cualquier
# usuario autenticado (no hay filtrado por usuario), así que la clave no lleva
# usuario; la autenticación se exige ANTES de llegar al handler (dependencia
# del router), por lo que una petición sin sesión nunca se sirve desde caché.
INCIDENT_CACHE_TTL_SECONDS = 30


def create_router(repository: IncidentRepository, prefix: str = "/api/incidents") -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["incidents"], dependencies=[Depends(get_current_user)])
    # Se cachea la proyección ya construida (IncidentListItem), no la lectura
    # cruda: construir miles de modelos Pydantic es la mayor parte del coste.
    list_cache: TTLCache[tuple[IncidentListItem, ...]] = TTLCache(INCIDENT_CACHE_TTL_SECONDS, max_entries=64)
    summary_cache: TTLCache[IncidentSummary] = TTLCache(INCIDENT_CACHE_TTL_SECONDS, max_entries=1)

    def invalidate_caches() -> None:
        list_cache.invalidate()
        summary_cache.invalidate()

    @router.post("", response_model=IncidentResponse, status_code=201)
    def create_incident(incident: IncidentCreate) -> IncidentResponse:
        created = IncidentResponse.model_validate(repository.create(incident))
        invalidate_caches()  # una incidencia nueva cambia listados y resumen
        return created

    @router.get("", response_model=list[IncidentListItem])
    def list_incidents(
        response: Response,
        status: str | None = Query(default=None),
        origin: str | None = Query(default=None),
        branch: str | None = Query(default=None),
        category: str | None = Query(default=None),
    ) -> list[IncidentListItem]:
        # Listas vacías (sin datos o sin coincidencias) son una respuesta
        # válida, no un error: el frontend decide cómo comunicarlo.
        def load() -> tuple[IncidentListItem, ...]:
            rows = repository.list(status=status, origin=origin, branch=branch, category=category)
            return tuple(IncidentListItem.model_validate(row) for row in rows)

        items, hit = list_cache.get_or_compute((status, origin, branch, category), load)
        response.headers["X-Cache"] = "HIT" if hit else "MISS"
        return list(items)

    @router.get("/summary", response_model=IncidentSummary)
    def incidents_summary(response: Response) -> IncidentSummary:
        summary, hit = summary_cache.get_or_compute("summary", lambda: IncidentSummary.model_validate(repository.summary()))
        response.headers["X-Cache"] = "HIT" if hit else "MISS"
        return summary

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
        invalidate_caches()  # el estado cambia en listados (filtro por estado) y en el resumen
        return IncidentResponse.model_validate(updated)

    return router
