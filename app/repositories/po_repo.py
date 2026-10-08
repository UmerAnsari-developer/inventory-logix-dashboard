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
