from datetime import datetime, timezone

from .models import SupplierCreate, SupplierCategory, SupplierStatus


def seed_suppliers() -> list[SupplierCreate]:
    seeded_at = datetime.now(timezone.utc)
    return [
        SupplierCreate(name="Carnes Andinas", categories=[SupplierCategory.CARNES], country="Colombia", rate=18.50, status=SupplierStatus.ACTIVO),
        SupplierCreate(name="Frigorífico La Sabana", categories=[SupplierCategory.CARNES], country="Colombia", rate=21.75, status=SupplierStatus.ACTIVO),
        SupplierCreate(name="Frescos del Valle", categories=[SupplierCategory.VEGETALES], country="Colombia", rate=4.20, status=SupplierStatus.ACTIVO),
        SupplierCreate(name="Lácteos de Antioquia", categories=[SupplierCategory.LACTEOS], country="Colombia", rate=3.80, status=SupplierStatus.ACTIVO),
        SupplierCreate(name="Empaques Sostenibles", categories=[SupplierCategory.EMPAQUES], country="Colombia", rate=0.35, status=SupplierStatus.ACTIVO),
        SupplierCreate(name="Florida Prime Meats", categories=[SupplierCategory.CARNES], country="Estados Unidos", rate=24.90, status=SupplierStatus.ACTIVO),
        SupplierCreate(name="Sunshine Produce", categories=[SupplierCategory.VEGETALES], country="Estados Unidos", rate=5.10, status=SupplierStatus.ACTIVO),
        SupplierCreate(name="Tropical Beverages", categories=[SupplierCategory.BEBIDAS], country="Estados Unidos", rate=2.45, status=SupplierStatus.ACTIVO),
        SupplierCreate(name="Orlando Cold Supply", categories=[SupplierCategory.BEBIDAS], country="Estados Unidos", rate=2.80, status=SupplierStatus.SUSPENDIDO),
        SupplierCreate(name="GreenPack Florida", categories=[SupplierCategory.EMPAQUES], country="Estados Unidos", rate=0.42, status=SupplierStatus.ACTIVO),
    ]