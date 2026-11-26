"""Gestión de proveedores y contratos: supervisor + especialista de precios + especialista de contratos (ver docs/supplier-contracts/)."""
from .engine import SupplierEngine
from .store import Store

__all__ = ["SupplierEngine", "Store"]
