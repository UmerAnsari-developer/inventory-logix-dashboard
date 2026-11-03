"""Purchase order repository via stored procedures."""
from __future__ import annotations

from ..database import get_cursor


class POError(ValueError):
    """Domain error for purchase-order operations (bad number, bad transition)."""


class PurchaseOrderRepository:
    @staticmethod
    def list_by_status(status: str | None = None) -> list[dict]:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_po_list_by_status(%s)", (status,))
            return list(cur.fetchall())

    @staticmethod
    def counts_by_status() -> dict[str, int]:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_po_counts_by_status()")
            return {row["status"]: int(row["cnt"]) for row in cur.fetchall()}

    @staticmethod
    def create(payload: dict) -> int:
        try:
            with get_cursor(commit=True) as cur:
                cur.execute(
                    "SELECT sp_po_create(%s,%s,%s,%s,%s,%s,%s)",
                    (
                        payload["po_number"], payload.get("supplier_id"),
                        payload.get("product_id"), int(payload.get("quantity") or 0),
                        float(payload.get("unit_cost") or 0),
                        payload.get("status") or "draft",
                        payload.get("eta_date"),
                    ),
                )
                return cur.fetchone()["sp_po_create"]
        except Exception as exc:
            # Race backstop: po_number is UNIQUE in the schema (fix DB-009).
            from ..security.dberrors import is_unique_violation
            if is_unique_violation(exc):
                raise POError(f"PO number {payload['po_number']} already exists.") from exc
            raise

    @staticmethod
    def transition(po_id: int, status: str) -> None:
        """Validated state-machine transition with stock/on_order effects (DB-003)."""
        try:
            with get_cursor(commit=True) as cur:
                cur.execute("SELECT sp_po_transition(%s, %s)", (po_id, status))
        except Exception as exc:
            from ..security.dberrors import db_error_message, is_guard_error
            if is_guard_error(exc, "Invalid PO transition", "Purchase order"):
                raise POError(db_error_message(exc)) from exc
            raise

    @staticmethod
    def receive(
        po_id: int,
        quantity: int,
        user_id: int,
        notes: str = "",
        location: str = "",
        idempotency_key: str | None = None
    ) -> None:
        """Receive goods for a PO (partial or full). Creates movement + goods_receipt.
        
        If idempotency_key is None, a fallback key is generated. HTTP callers
        should pass the request's idempotency key so that duplicate submissions
        are deduped at the DB level (P0 idempotency fix).
        """
        try:
            import uuid
            if idempotency_key is None:
                idempotency_key = f"recv-{po_id}-{uuid.uuid4().hex[:16]}"
            with get_cursor(commit=True) as cur:
                cur.execute(
                    "SELECT sp_po_transition(%s, %s, %s, %s, %s, %s, %s)",
                    (po_id, "received", quantity, user_id, notes, location, idempotency_key)
                )
        except Exception as exc:
            from ..security.dberrors import db_error_message, is_guard_error
            if is_guard_error(exc, "Invalid PO transition", "Purchase order"):
                raise POError(db_error_message(exc)) from exc
            if "exceeds outstanding" in str(exc):
                raise POError(f"Receive quantity exceeds outstanding: {exc}") from exc
            if "not found or not in_transit" in str(exc):
                raise POError(f"PO not found or not in in_transit status: {exc}") from exc
            if "User" in str(exc) and "not found" in str(exc):
                raise POError(f"User not found: {exc}") from exc
            raise

    @staticmethod
    def list_receipts(
        po_id: int | None = None,
        received_by: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None
    ) -> list[dict]:
        """List goods receipts with optional filters."""
        with get_cursor() as cur:
            cur.execute(
                "SELECT * FROM sp_goods_receipt_list(%s, %s, %s, %s)",
                (po_id, received_by, date_from, date_to)
            )
            return list(cur.fetchall())
