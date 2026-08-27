from datetime import datetime
from enum import Enum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class SupplierCategory(str, Enum):
    CARNES = "Carnes"
    VEGETALES = "Vegetales"
    LACTEOS = "Lácteos"
    BEBIDAS = "Bebidas"
    EMPAQUES = "Empaques"


class SupplierStatus(str, Enum):
    ACTIVO = "Activo"
    SUSPENDIDO = "Suspendido"


class SupplierBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1)
    categories: list[SupplierCategory] = Field(min_length=1, validation_alias=AliasChoices("categories", "product_category"))
    country: str = Field(min_length=1)
    rate: float = Field(gt=0, validation_alias=AliasChoices("rate", "current_rate"))
    status: SupplierStatus


class SupplierCreate(SupplierBase):
    pass


class Supplier(SupplierBase):
    id: int = Field(gt=0)
    updated_at: datetime


class RateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate: float = Field(gt=0, validation_alias=AliasChoices("rate", "current_rate"))


class StatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SupplierStatus