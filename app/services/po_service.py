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