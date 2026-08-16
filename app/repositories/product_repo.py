"""Product repository: persistence for the ``products`` table."""
from __future__ import annotations

from typing import Any

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
    """CRUD operations for ``products``."""

    _BASE_SELECT = (
        "p.id, p.sku, p.name, p.category, p.warehouse, p.current_stock, "
        "p.reorder_point, p.demand_rate, p.ordering_cost, p.holding_cost, "
        "p.unit_price, p.supplier_id, p.on_order, p.created_at, p.updated_at, "
        "s.name AS supplier_name, s.tone AS supplier_tone, s.lead_days"
    )

    @classmethod
    def _join(cls) -> str:
        return (
            "FROM products p LEFT JOIN suppliers s ON s.id = p.supplier_id"
        )

    @classmethod
    def list(cls, *, search: str = "", category: str = "", status: str = "",
             warehouse: str = "", limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        where, params = [], []
        if search:
            where.append("(p.sku ILIKE %s OR p.name ILIKE %s OR p.category ILIKE %s OR s.name ILIKE %s)")
            params.extend([f"%{search}%"] * 4)
        if category:
            where.append("p.category = %s")
            params.append(category)
        if warehouse:
            where.append("p.warehouse = %s")
            params.append(warehouse)
        if status == "ok":
            where.append("p.current_stock > p.reorder_point")
        elif status == "low":
            where.append("p.current_stock <= p.reorder_point AND p.current_stock > 0")
        elif status == "out":
            where.append("p.current_stock <= 0")
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        with get_cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS c {cls._join()} {where_sql}", params)
            total = cur.fetchone()["c"]
            cur.execute(
                f"SELECT {cls._BASE_SELECT} {cls._join()} {where_sql} "
                "ORDER BY p.sku LIMIT %s OFFSET %s",
                params + [limit, offset],
            )
            rows = [_decorate(r) for r in cur.fetchall()]
        return rows, total

    @classmethod
    def find(cls, product_id: int) -> dict | None:
        with get_cursor() as cur:
            cur.execute(f"SELECT {cls._BASE_SELECT} {cls._join()} WHERE p.id = %s", (product_id,))
            row = cur.fetchone()
        return _decorate(row) if row else None

    @classmethod
    def find_by_sku(cls, sku: str) -> dict | None:
        with get_cursor() as cur:
            cur.execute(f"SELECT {cls._BASE_SELECT} {cls._join()} WHERE p.sku = %s", (sku,))
            row = cur.fetchone()
        return _decorate(row) if row else None

    @classmethod
    def create(cls, payload: dict) -> int:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO products
                    (sku, name, category, warehouse, current_stock, reorder_point,
                     demand_rate, ordering_cost, holding_cost, unit_price, supplier_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """,
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
            return cur.fetchone()["id"]

    @classmethod
    def update(cls, product_id: int, payload: dict) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE products SET
                    name = %s, category = %s, warehouse = %s,
                    unit_price = %s, supplier_id = %s,
                    current_stock = %s, reorder_point = %s,
                    demand_rate = %s, ordering_cost = %s, holding_cost = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    payload["name"], payload.get("category"),
                    payload.get("warehouse"), payload.get("unit_price"),
                    payload.get("supplier_id"), int(payload.get("current_stock") or 0),
                    int(payload.get("reorder_point") or 0),
                    payload.get("demand_rate"), payload.get("ordering_cost"),
                    payload.get("holding_cost"), product_id,
                ),
            )

    @classmethod
    def delete(cls, product_id: int) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute("DELETE FROM products WHERE id = %s", (product_id,))

    @classmethod
    def set_stock(cls, product_id: int, value: int) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE products SET current_stock = %s, updated_at = NOW() WHERE id = %s",
                (value, product_id),
            )

    @classmethod
    def set_on_order(cls, product_id: int, qty: int) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE products SET on_order = %s, updated_at = NOW() WHERE id = %s",
                (qty, product_id),
            )

    @classmethod
    def categories(cls) -> list[str]:
        with get_cursor() as cur:
            cur.execute(
                "SELECT DISTINCT category FROM products WHERE category IS NOT NULL ORDER BY category"
            )
            return [row["category"] for row in cur.fetchall()]

    @classmethod
    def warehouses(cls) -> list[str]:
        with get_cursor() as cur:
            cur.execute(
                "SELECT DISTINCT warehouse FROM products WHERE warehouse IS NOT NULL ORDER BY warehouse"
            )
            return [row["warehouse"] for row in cur.fetchall()]

    @classmethod
    def low_stock(cls) -> list[dict]:
        with get_cursor() as cur:
            cur.execute(
                f"SELECT {cls._BASE_SELECT} {cls._join()} "
                "WHERE p.current_stock <= p.reorder_point AND p.on_order <= 0 "
                "ORDER BY (p.reorder_point - p.current_stock) DESC",
            )
            return [_decorate(r) for r in cur.fetchall()]
