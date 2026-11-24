from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth.dependencies import get_current_user
from ..security import require_confirmation, require_manager_or_admin
from .models import RateUpdate, StatusUpdate, SupplierCreate, SupplierResponse
from .repository import SupplierRepository


def create_router(repository: SupplierRepository, prefix: str = "/api/suppliers") -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["suppliers"], dependencies=[Depends(get_current_user)])

    @router.get("", response_model=list[SupplierResponse])
    def list_suppliers(
        country: str | None = Query(default=None),
        category: str | None = Query(default=None),
    ) -> list[SupplierResponse]:
        return [SupplierResponse.model_validate(item) for item in repository.list(country=country, category=category)]

    @router.get("/country/{country}", response_model=list[SupplierResponse])
    def suppliers_by_country(country: str) -> list[SupplierResponse]:
        return [SupplierResponse.model_validate(item) for item in repository.list(country=country)]

    @router.get("/category/{category}", response_model=list[SupplierResponse])
    def suppliers_by_category(category: str) -> list[SupplierResponse]:
        return [SupplierResponse.model_validate(item) for item in repository.list(category=category)]

    @router.get("/{supplier_id}", response_model=SupplierResponse)
    def get_supplier(supplier_id: str) -> SupplierResponse:
        supplier = repository.get(supplier_id)
        if supplier is None:
            raise HTTPException(status_code=404, detail="Proveedor no encontrado")
        return SupplierResponse.model_validate(supplier)

    @router.post("", response_model=SupplierResponse, status_code=201, dependencies=[Depends(require_manager_or_admin)])
    def create_supplier(supplier: SupplierCreate) -> SupplierResponse:
        return SupplierResponse.model_validate(repository.create(supplier))

    @router.patch("/{supplier_id}/rate", response_model=SupplierResponse, dependencies=[Depends(require_manager_or_admin)])
    def update_supplier_rate(supplier_id: str, update: RateUpdate) -> SupplierResponse:
        supplier = repository.update_rate(supplier_id, update)
        if supplier is None:
            raise HTTPException(status_code=404, detail="Proveedor no encontrado")
        return SupplierResponse.model_validate(supplier)

    @router.patch("/{supplier_id}/status", response_model=SupplierResponse, dependencies=[Depends(require_manager_or_admin)])
    def update_supplier_status(supplier_id: str, update: StatusUpdate, confirm: bool = Query(default=False)) -> SupplierResponse:
        require_confirmation(confirm, "Cambiar el estado de un proveedor")  # BRIEFING §5: acción con confirmación humana
        supplier = repository.update_status(supplier_id, update)
        if supplier is None:
            raise HTTPException(status_code=404, detail="Proveedor no encontrado")
        return SupplierResponse.model_validate(supplier)

    @router.delete("/{supplier_id}", status_code=204, response_model=None, dependencies=[Depends(require_manager_or_admin)])
    def delete_supplier(supplier_id: str, confirm: bool = Query(default=False)) -> None:
        require_confirmation(confirm, "Dar de baja a un proveedor")  # BRIEFING §5: acción con confirmación humana
        if not repository.delete(supplier_id):
            raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    return router