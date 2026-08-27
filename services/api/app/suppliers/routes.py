from fastapi import APIRouter, HTTPException, Query

from .models import RateUpdate, StatusUpdate, Supplier, SupplierCreate
from .repository import SupplierRepository


def create_router(repository: SupplierRepository, prefix: str = "/api/suppliers") -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["suppliers"])

    @router.get("", response_model=list[Supplier])
    def list_suppliers(
        country: str | None = Query(default=None),
        category: str | None = Query(default=None),
    ) -> list[Supplier]:
        return repository.list(country=country, category=category)

    @router.get("/country/{country}", response_model=list[Supplier])
    def suppliers_by_country(country: str) -> list[Supplier]:
        return repository.list(country=country)

    @router.get("/category/{category}", response_model=list[Supplier])
    def suppliers_by_category(category: str) -> list[Supplier]:
        return repository.list(category=category)

    @router.get("/{supplier_id}", response_model=Supplier)
    def get_supplier(supplier_id: str) -> Supplier:
        supplier = repository.get(supplier_id)
        if supplier is None:
            raise HTTPException(status_code=404, detail="Proveedor no encontrado")
        return supplier

    @router.post("", response_model=Supplier, status_code=201)
    def create_supplier(supplier: SupplierCreate) -> Supplier:
        return repository.create(supplier)

    @router.patch("/{supplier_id}/rate", response_model=Supplier)
    def update_supplier_rate(supplier_id: str, update: RateUpdate) -> Supplier:
        supplier = repository.update_rate(supplier_id, update)
        if supplier is None:
            raise HTTPException(status_code=404, detail="Proveedor no encontrado")
        return supplier

    @router.patch("/{supplier_id}/status", response_model=Supplier)
    def update_supplier_status(supplier_id: str, update: StatusUpdate) -> Supplier:
        supplier = repository.update_status(supplier_id, update)
        if supplier is None:
            raise HTTPException(status_code=404, detail="Proveedor no encontrado")
        return supplier

    @router.delete("/{supplier_id}", status_code=204)
    def delete_supplier(supplier_id: str) -> None:
        if not repository.delete(supplier_id):
            raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    return router