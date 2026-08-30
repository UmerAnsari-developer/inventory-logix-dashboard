"""Purchase order repository via stored procedures."""
from __future__ import annotations

from ..database import get_cursor


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

    @staticmethod
    def update_status(po_id: int, status: str) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_po_update_status(%s, %s)", (po_id, status))
