"""Movement service.

Stock correctness is enforced inside ``sp_movement_record`` (row lock + stock
floor + delta update + insert, all in one transaction — fix DB-002). The
pre-check below exists only for friendly, early error messages; on a real race
the database guard fires and is translated back into ``MovementError``.
"""
from __future__ import annotations

from ..repositories import ProductRepository, MovementRepository, AuditRepository
from ..security.dberrors import db_error_message, is_guard_error

# Guard messages raised by sp_movement_record / trg_validate_movement.
_STOCK_GUARDS = (
    "Insufficient stock",
    "Invalid product_id",
    "Invalid movement type",
    "Adjustment would create negative stock",
)


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

        product = ProductRepository.find(product_id)
        if not product:
            raise MovementError("Product not found.")

        # Early (non-authoritative) balance check so the common case fails fast
        # with the historical message. The authoritative check happens under the
        # product row lock inside sp_movement_record.
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

        try:
            movement_id = MovementRepository.record(
                product_id=product_id,
                mtype=mtype,
                quantity=int(quantity),
                reference=(reference or "").strip() or None,
                notes=(notes or "").strip() or None,
                user_id=user_id,
            )
        except Exception as exc:
            if is_guard_error(exc, *_STOCK_GUARDS):
                raise MovementError(db_error_message(exc)) from exc
            raise

        # DB-072: audit + notification are best-effort AFTER the movement commit —
        # a crash between them loses the audit row but never the stock/ledger state.
        # Full outbox pattern deferred (single-worker deployment; ceiling documented).
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
                # Value from the pre-check read; under a concurrent write the
                # database balance is authoritative (audit is informational).
                "new_stock": new_stock,
            },
        )

        # Send notification
        try:
            from .notification_service import notify_movement
            notify_movement(
                sku=product["sku"],
                product_name=product["name"],
                movement_type=mtype,
                qty=int(quantity),
                warehouse=product.get("warehouse", ""),
            )
        except Exception:
            pass

        return movement_id
