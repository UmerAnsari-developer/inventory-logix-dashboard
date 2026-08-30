"""Movement service."""
from __future__ import annotations

from ..repositories import ProductRepository, MovementRepository, AuditRepository


class MovementError(ValueError):
    pass


class MovementService:
    ALLOWED_TYPES = {"IN", "OUT", "ADJUSTMENT", "RETURN"}

    @classmethod
    def record(cls, *, product_id: int, mtype: str, quantity: int,
               reference: str | None = None, notes: str | None = None,
               user_id: int | None = None) -> int:
        if not product_id:
            raise MovementError("Product is required.")
        if mtype not in cls.ALLOWED_TYPES:
            raise MovementError(f"Type must be one of {sorted(cls.ALLOWED_TYPES)}.")
        if quantity is None or int(quantity) <= 0:
            raise MovementError("Quantity must be a positive integer.")

        product = ProductRepository.find_for_update(product_id)
        if not product:
            raise MovementError("Product not found.")

        new_stock = int(product["current_stock"] or 0)
        if mtype == "OUT":
            if new_stock - int(quantity) < 0:
                raise MovementError("Stock-out would create a negative balance.")
            new_stock -= int(quantity)
        elif mtype == "ADJUSTMENT":
            if new_stock + int(quantity) < 0:
                raise MovementError("Adjustment would create a negative balance.")
            new_stock += int(quantity)
        else:
            new_stock += int(quantity)

        movement_id = MovementRepository.record(
            product_id=product_id,
            sku=product["sku"],
            mtype=mtype,
            quantity=int(quantity),
            reference=(reference or "").strip() or None,
            notes=(notes or "").strip() or None,
            user_id=user_id,
        )
        ProductRepository.set_stock(product_id, new_stock)
        AuditRepository.record(
            user_id,
            "movement.record",
            target_type="movement",
            target_id=movement_id,
            detail={
                "product_id": product_id,
                "sku": product["sku"],
                "type": mtype,
                "quantity": int(quantity),
                "new_stock": new_stock,
            },
        )
        return movement_id
