"""Product repository: persistence for the ``products`` table via stored procedures."""
from __future__ import annotations

from ..database import get_cursor
from ..utils import calculate_eoq, stock_status


def _decorate(row: dict) -> dict:
    row = dict(row)
    low_pct, critical_pct = 20.0, 10.0
    try:
        from ..services.settings_service import SettingsService
        low_pct, critical_pct = SettingsService.threshold_pcts()
    except Exception:
        pass
    status, label = stock_status(
        int(row.get("current_stock") or 0),
        int(row.get("reorder_point") or 0),
        low_pct=low_pct,
        critical_pct=critical_pct,
    )
    row["status"] = status
    row["status_label"] = label
    _eoq = calculate_eoq(
        row.get("demand_rate"), row.get("ordering_cost"), row.get("holding_cost")
    )
    row["eoq"] = round(_eoq) if _eoq else None
    if row.get("name"):
        parts = [p for p in row["name"].split() if p]
        row["initials"] = (
            (parts[0][0] + parts[1][0]).upper()
            if len(parts) >= 2
            else (row["name"][:2] or "??").upper()
        )
    stock = int(row.get("current_stock") or 0)
    rop = int(row.get("reorder_point") or 0)
    denom = max(rop * 1.65, stock) or 1
    row["runway_ratio"] = round(min(100, max(4, (stock / denom) * 100)))
    row["rop_ratio"] = round(min(94, max(8, (rop / denom) * 100)))
    return row


class ProductRepository:
    """CRUD operations for ``products`` via stored procedures."""

    @classmethod
    def list(cls, *, search: str = "", category: str = "", status: str = "",
             warehouse: str = "", limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        with get_cursor() as cur:
            cur.execute(
                "SELECT * FROM sp_product_list(%s, %s, %s, %s, %s, %s)",
                (search, category, warehouse, status, limit, offset),
            )
            rows = cur.fetchall()
        total = rows[0]["total_count"] if rows else 0
        return [_decorate(r) for r in rows], total

    @classmethod
    def find(cls, product_id: int) -> dict | None:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_product_find(%s)", (product_id,))
            row = cur.fetchone()
        return _decorate(row) if row else None

    @classmethod
    def find_by_sku(cls, sku: str) -> dict | None:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_product_find_by_sku(%s)", (sku,))
            row = cur.fetchone()
        return _decorate(row) if row else None

    @classmethod
    def create(cls, payload: dict) -> int:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "SELECT sp_product_create(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    payload["sku"], payload["name"], payload.get("category"),
                    payload.get("warehouse") or "WH-Pune",
                    int(payload.get("current_stock") or 0),
                    int(payload.get("reorder_point") or 0),
                    payload.get("demand_rate"), payload.get("ordering_cost"),
                    payload.get("holding_cost"), payload.get("unit_price"),
                    payload.get("supplier_id"),
                ),
            )
            return cur.fetchone()["sp_product_create"]

    @classmethod
    def update(cls, product_id: int, payload: dict) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "SELECT sp_product_update(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    product_id,
                    payload["name"], payload.get("category"),
                    payload.get("warehouse"), payload.get("unit_price"),
                    payload.get("supplier_id"), int(payload.get("current_stock") or 0),
                    int(payload.get("reorder_point") or 0),
                    payload.get("demand_rate"), payload.get("ordering_cost"),
                    payload.get("holding_cost"),
                ),
            )

    @classmethod
    def delete(cls, product_id: int) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_product_delete(%s)", (product_id,))

    @classmethod
    def find_for_update(cls, product_id: int) -> dict | None:
        """Select product row with FOR UPDATE lock to prevent concurrent overdraw."""
        with get_cursor() as cur:
            cur.execute("SELECT * FROM products WHERE id = %s FOR UPDATE", (product_id,))
            return cur.fetchone()

    @classmethod
    def set_stock(cls, product_id: int, value: int) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_product_set_stock(%s, %s)", (product_id, value))

    @classmethod
    def set_on_order(cls, product_id: int, qty: int) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_product_set_on_order(%s, %s)", (product_id, qty))

    @classmethod
    def categories(cls) -> list[str]:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_product_categories()")
            return [row["category"] for row in cur.fetchall()]

    @classmethod
    def warehouses(cls) -> list[str]:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_product_warehouses()")
            return [row["warehouse"] for row in cur.fetchall()]

    @classmethod
    def low_stock(cls) -> list[dict]:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_product_low_stock()")
            return [_decorate(r) for r in cur.fetchall()]
