"""Purchase Order service — orchestrates the PO repository with validation."""
from __future__ import annotations

from ..repositories import PurchaseOrderRepository, POError
from ..security.validators import ValidationError, validate_positive_number


class POServiceError(ValueError):
    pass


class POService:
    @staticmethod
    def validate_payload(payload: dict) -> dict:
        """Validate and normalize PO payload."""
        try:
            # Required fields
            po_number = payload.get("po_number", "").strip() if payload.get("po_number") else ""
            if not po_number:
                raise ValidationError("PO number is required.")
            if len(po_number) > 50:
                raise ValidationError("PO number must be at most 50 characters.")
            payload["po_number"] = po_number

            supplier_id = payload.get("supplier_id")
            if supplier_id is None or supplier_id == "":
                raise ValidationError("Supplier is required.")
            payload["supplier_id"] = int(supplier_id)

            product_id = payload.get("product_id")
            if product_id is None or product_id == "":
                raise ValidationError("Product is required.")
            payload["product_id"] = int(product_id)

            quantity = payload.get("quantity")
            if quantity is None or quantity == "":
                raise ValidationError("Quantity is required.")
            payload["quantity"] = validate_positive_number(quantity, "Quantity", allow_zero=False)

            unit_cost = payload.get("unit_cost")
            if unit_cost is None or unit_cost == "":
                raise ValidationError("Unit cost is required.")
            payload["unit_cost"] = validate_positive_number(unit_cost, "Unit cost", allow_zero=True)

            status = payload.get("status", "draft").strip().lower()
            valid_statuses = ("draft", "approved", "in_transit", "received", "cancelled")
            if status not in valid_statuses:
                raise ValidationError(f"Invalid status. Must be one of: {', '.join(valid_statuses)}")
            payload["status"] = status

            eta_date = payload.get("eta_date")
            if eta_date == "":
                payload["eta_date"] = None
            # Keep as string for DB, validation happens at DB level

        except ValidationError as exc:
            raise POServiceError(str(exc)) from exc
        return payload

    @classmethod
    def create(cls, payload: dict) -> int:
        """Create a new purchase order."""
        payload = cls.validate_payload(payload)
        try:
            return PurchaseOrderRepository.create(payload)
        except POError:
            raise
        except Exception as exc:
            # Race backstop: po_number is UNIQUE in the schema
            from ..security.dberrors import is_unique_violation
            if is_unique_violation(exc):
                raise POServiceError(f"PO number {payload['po_number']} already exists.") from exc
            raise

    @classmethod
    def transition(cls, po_id: int, status: str) -> None:
        """Transition PO through state machine."""
        PurchaseOrderRepository.transition(po_id, status)

    @classmethod
    def receive(
        cls,
        po_id: int,
        quantity: int,
        user_id: int,
        notes: str = "",
        location: str = "",
        idempotency_key: str | None = None
    ) -> None:
        """Receive goods for a PO with validation."""
        # Validate quantity > 0
        if quantity <= 0:
            raise POServiceError("Quantity must be positive.")
        
        # Validate user exists
        from ..repositories import UserRepository
        user = UserRepository.find_by_id(user_id)
        if not user:
            raise POServiceError(f"User {user_id} not found.")
        
        # Validate PO exists and is in_transit
        from ..database.connection import get_cursor
        with get_cursor() as cur:
            cur.execute(
                "SELECT id, status, quantity, received_quantity FROM purchase_orders WHERE id = %s AND deleted_at IS NULL",
                (po_id,)
            )
            po = cur.fetchone()
            if not po:
                raise POServiceError(f"Purchase order {po_id} not found.")
            if po["status"] != "in_transit":
                raise POServiceError(f"Invalid PO transition: {po['status']} -> received")
            outstanding = po["quantity"] - (po["received_quantity"] or 0)
            if quantity > outstanding:
                raise POServiceError(f"Receive quantity {quantity} exceeds outstanding {outstanding}.")
        
        # Delegate to repository (handles idempotency key generation/forwarding)
        try:
            PurchaseOrderRepository.receive(po_id, quantity, user_id, notes, location, idempotency_key)
        except POError as exc:
            raise POServiceError(str(exc)) from exc
        except Exception as exc:
            # Wrap SP-level idempotency conflict
            if "Idempotency key" in str(exc) and "reused with different" in str(exc):
                raise POServiceError(str(exc)) from exc
            raise

    @classmethod
    def list_receipts(
        cls,
        po_id: int | None = None,
        received_by: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None
    ) -> list[dict]:
        """List goods receipts with optional filters."""
        return PurchaseOrderRepository.list_receipts(po_id, received_by, date_from, date_to)