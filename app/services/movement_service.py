"""Movement service.

Stock correctness is enforced inside ``sp_movement_record`` (row lock + stock
floor + delta update + insert, all in one transaction — fix DB-002). The
pre-check below exists only for friendly, early error messages; on a real race
the database guard fires and is translated back into ``MovementError``.
"""
from __future__ import annotations

from datetime import datetime
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

    @classmethod
    def list_movements(
        cls,
        type_filter: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        product_id: int | None = None,
        user_id: int | None = None,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> list[dict]:
        """List movements with filters, pagination, and sorting."""
        # Validate pagination
        if page < 1:
            raise MovementError("Page must be >= 1")
        if per_page < 1:
            raise MovementError("Per page must be >= 1")
        if per_page > 100:
            per_page = 100

        # Validate sort_by
        valid_sort_fields = {"created_at", "type", "product", "user", "quantity"}
        if sort_by not in valid_sort_fields:
            raise MovementError(f"sort_by must be one of {sorted(valid_sort_fields)}")

        # Validate sort_order
        if sort_order not in ("asc", "desc"):
            raise MovementError("Sort order must be 'asc' or 'desc'")

        # Validate type_filter
        if type_filter is not None:
            if not isinstance(type_filter, list):
                type_filter = [type_filter]
            for t in type_filter:
                if t not in cls.ALLOWED_TYPES:
                    raise MovementError(f"Invalid type: {t}. Must be one of {sorted(cls.ALLOWED_TYPES)}")

        # Validate date formats (ISO 8601)
        if date_from is not None:
            try:
                datetime.fromisoformat(date_from.replace('Z', '+00:00'))
            except ValueError:
                raise MovementError("date_from must be ISO 8601 format")
        if date_to is not None:
            try:
                datetime.fromisoformat(date_to.replace('Z', '+00:00'))
            except ValueError:
                raise MovementError("date_to must be ISO 8601 format")

        # Validate product_id
        if product_id is not None and not isinstance(product_id, int):
            raise MovementError("product_id must be an integer")

        # Validate user_id
        if user_id is not None and not isinstance(user_id, int):
            raise MovementError("user_id must be an integer")

        return MovementRepository.list_movements(
            type_filter=type_filter,
            date_from=date_from,
            date_to=date_to,
            product_id=product_id,
            user_id=user_id,
            page=page,
            per_page=per_page,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    @classmethod
    def get_movement_count(
        cls,
        type_filter: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        product_id: int | None = None,
        user_id: int | None = None,
    ) -> int:
        """Get total count of movements matching filters."""
        if type_filter is not None:
            if not isinstance(type_filter, list):
                type_filter = [type_filter]
            for t in type_filter:
                if t not in cls.ALLOWED_TYPES:
                    raise MovementError(f"Invalid type: {t}. Must be one of {sorted(cls.ALLOWED_TYPES)}")

        if date_from is not None:
            try:
                datetime.fromisoformat(date_from.replace('Z', '+00:00'))
            except ValueError:
                raise MovementError("date_from must be ISO 8601 format")
        if date_to is not None:
            try:
                datetime.fromisoformat(date_to.replace('Z', '+00:00'))
            except ValueError:
                raise MovementError("date_to must be ISO 8601 format")

        if product_id is not None and not isinstance(product_id, int):
            raise MovementError("product_id must be an integer")
        if user_id is not None and not isinstance(user_id, int):
            raise MovementError("user_id must be an integer")

        return MovementRepository.get_movement_count(
            type_filter=type_filter,
            date_from=date_from,
            date_to=date_to,
            product_id=product_id,
            user_id=user_id,
        )

    @classmethod
    def export_movements(
        cls,
        type_filter: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        product_id: int | None = None,
        user_id: int | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        limit: int = 5000,
    ):
        """Export movements as CSV generator."""
        # Validate limit
        if limit < 1:
            raise MovementError("Limit must be >= 1")
        if limit > 5000:
            limit = 5000

        # Validate sort_by
        valid_sort_fields = {"created_at", "type", "product", "user", "quantity"}
        if sort_by not in valid_sort_fields:
            raise MovementError(f"sort_by must be one of {sorted(valid_sort_fields)}")

        # Validate sort_order
        if sort_order not in ("asc", "desc"):
            raise MovementError("sort_order must be 'asc' or 'desc'")

        # Reuse list_movements validation for filters
        if type_filter is not None:
            if not isinstance(type_filter, list):
                type_filter = [type_filter]
            for t in type_filter:
                if t not in cls.ALLOWED_TYPES:
                    raise MovementError(f"Invalid type: {t}. Must be one of {sorted(cls.ALLOWED_TYPES)}")

        if date_from is not None:
            try:
                datetime.fromisoformat(date_from.replace('Z', '+00:00'))
            except ValueError:
                raise MovementError("date_from must be ISO 8601 format")
        if date_to is not None:
            try:
                datetime.fromisoformat(date_to.replace('Z', '+00:00'))
            except ValueError:
                raise MovementError("date_to must be ISO 8601 format")

        if product_id is not None and not isinstance(product_id, int):
            raise MovementError("product_id must be an integer")
        if user_id is not None and not isinstance(user_id, int):
            raise MovementError("user_id must be an integer")

        return MovementRepository.export_movements(
            type_filter=type_filter,
            date_from=date_from,
            date_to=date_to,
            product_id=product_id,
            user_id=user_id,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
        )

    @classmethod
    def get_product_movements(cls, product_id: int, **kwargs) -> list[dict]:
        """Get movements for a specific product with optional filters."""
        if not isinstance(product_id, int):
            raise MovementError("product_id must be an integer")

        # Verify product exists
        from ..repositories import ProductRepository
        product = ProductRepository.find(product_id)
        if not product:
            raise MovementError(f"Product {product_id} not found")

        # Add product_id to filters and delegate to list_movements
        kwargs['product_id'] = product_id
        return cls.list_movements(**kwargs)
