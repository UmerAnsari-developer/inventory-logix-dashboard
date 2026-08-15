"""Warehouse repository — reads analytics from the star-schema warehouse.

The facts/dimensions are maintained by the ETL in ``app/database/etl.py``.
"""
from __future__ import annotations

from ..database import get_cursor


class WarehouseRepository:
    """Queries over ``dim_warehouse`` / ``fact_*`` for warehouse analytics."""

    @staticmethod
    def latest_snapshot_date():
        with get_cursor() as cur:
            cur.execute("SELECT MAX(date_key) AS latest FROM fact_inventory_daily")
            return cur.fetchone()["latest"]

    @staticmethod
    def analytics():
        """Per-warehouse snapshot for the latest date in the star schema.

        Returns ``None`` when the warehouse has not been built yet, so callers
        can fall back to operational tables.
        """
        latest = WarehouseRepository.latest_snapshot_date()
        if not latest:
            return None
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT dw.warehouse_name AS warehouse,
                       dw.warehouse_code,
                       dw.city,
                       dw.region,
                       COUNT(*) AS sku_count,
                       COALESCE(SUM(f.stock_on_hand), 0) AS total_units,
                       COALESCE(SUM(f.inventory_value), 0) AS total_value,
                       COALESCE(SUM(CASE WHEN f.stock_on_hand > 0
                                          AND f.stock_on_hand <= f.reorder_point
                                         THEN 1 ELSE 0 END), 0) AS low_count,
                       COALESCE(SUM(CASE WHEN f.stock_on_hand <= 0 THEN 1 ELSE 0 END), 0) AS critical_count
                FROM fact_inventory_daily f
                JOIN dim_warehouse dw ON dw.warehouse_key = f.warehouse_key
                WHERE f.date_key = %s
                GROUP BY dw.warehouse_key, dw.warehouse_name, dw.warehouse_code, dw.city, dw.region
                ORDER BY total_value DESC
                """,
                (latest,),
            )
            return list(cur.fetchall())

    @staticmethod
    def movement_summary(days: int = 30):
        """In/out/net movement totals per warehouse over the last ``days``."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT dw.warehouse_name AS warehouse,
                       COALESCE(SUM(f.in_qty), 0) AS in_qty,
                       COALESCE(SUM(f.out_qty), 0) AS out_qty,
                       COALESCE(SUM(f.net_qty), 0) AS net_qty,
                       COALESCE(SUM(f.in_value), 0) AS in_value,
                       COALESCE(SUM(f.out_value), 0) AS out_value
                FROM fact_movement_daily f
                JOIN dim_warehouse dw ON dw.warehouse_key = f.warehouse_key
                WHERE f.date_key >= CURRENT_DATE - %s::int
                GROUP BY dw.warehouse_key, dw.warehouse_name
                ORDER BY warehouse_name
                """,
                (days,),
            )
            return list(cur.fetchall())

    @staticmethod
    def is_ready() -> bool:
        return WarehouseRepository.latest_snapshot_date() is not None