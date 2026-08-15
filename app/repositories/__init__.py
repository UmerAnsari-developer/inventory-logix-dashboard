"""Repository layer — SQL queries live here, one module per entity."""
from .user_repo import UserRepository
from .product_repo import ProductRepository
from .supplier_repo import SupplierRepository
from .movement_repo import MovementRepository
from .audit_repo import AuditRepository
from .po_repo import PurchaseOrderRepository
from .forecast_repo import ForecastRepository, AnomalyRepository
from .settings_repo import SettingsRepository
from .warehouse_repo import WarehouseRepository

__all__ = [
    "UserRepository",
    "ProductRepository",
    "SupplierRepository",
    "MovementRepository",
    "AuditRepository",
    "PurchaseOrderRepository",
    "ForecastRepository",
    "AnomalyRepository",
    "SettingsRepository",
    "WarehouseRepository",
]
