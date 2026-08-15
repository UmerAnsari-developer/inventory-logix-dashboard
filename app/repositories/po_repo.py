"""Purchase order repository."""
from __future__ import annotations

from datetime import date

from ..database import get_cursor


class PurchaseOrderRepository:
    @staticmethod
    def list_by_status(status: str | None = None) -> list[dict]:
        sql = (
            "SELECT po.*, s.name AS supplier_name, p.name AS product_name, p.sku "
            "FROM purchase_orders po "
            "LEFT JOIN suppliers s ON s.id = po.supplier_id "
            "LEFT JOIN products p ON p.id = po.product_id "
        )
        params: tuple = ()
        if status and status != "all":
            sql += "WHERE po.status = %s "
            params = (status,)
        sql += "ORDER BY po.created_at DESC"
        with get_cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    @staticmethod
    def counts_by_status() -> dict[str, int]:
        with get_cursor() as cur:
            cur.execute(
                "SELECT status, COUNT(*) AS c FROM purchase_orders GROUP BY status"
            )
            return {row["status"]: int(row["c"]) for row in cur.fetchall()}

    @staticmethod
    def create(payload: dict) -> int:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO purchase_orders
                    (po_number, supplier_id, product_id, quantity, unit_cost, status, eta_date)
                VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """,
                (
                    payload["po_number"], payload.get("supplier_id"),
                    payload.get("product_id"), int(payload.get("quantity") or 0),
                    float(payload.get("unit_cost") or 0),
                    payload.get("status") or "draft",
                    payload.get("eta_date") or date.today(),
                ),
            )
            return cur.fetchone()["id"]

    @staticmethod
    def update_status(po_id: int, status: str) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE purchase_orders SET status=%s, updated_at=NOW() WHERE id=%s",
                (status, po_id),
            )
