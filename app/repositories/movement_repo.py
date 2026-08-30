"""Movement repository via stored procedures."""
from __future__ import annotations

from ..database import get_cursor


class MovementRepository:
    @staticmethod
    def recent_for_product(product_id: int, limit: int = 10) -> list[dict]:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_movement_recent_for_product(%s, %s)", (product_id, limit))
            return list(cur.fetchall())

    @staticmethod
    def daily_totals(days: int = 14) -> list[dict]:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_movement_daily_totals(%s)", (days,))
            return list(cur.fetchall())

    @staticmethod
    def daily_for_product(product_id: int, days: int = 90) -> list[dict]:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_movement_daily_for_product(%s, %s)", (product_id, days))
            return list(cur.fetchall())

    @staticmethod
    def units_today() -> int:
        with get_cursor() as cur:
            cur.execute("SELECT sp_movement_units_today()")
            return int(cur.fetchone()["sp_movement_units_today"] or 0)

    @staticmethod
    def record(product_id: int, sku: str, mtype: str, quantity: int,
               reference: str | None = None, notes: str | None = None,
               user_id: int | None = None) -> int:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "SELECT sp_movement_record(%s, %s, %s, %s, %s, %s, %s)",
                (product_id, sku, mtype, quantity, reference, notes, user_id),
            )
            return cur.fetchone()["sp_movement_record"]
