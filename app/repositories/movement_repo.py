"""Movement repository."""
from __future__ import annotations

from datetime import date, timedelta

from ..database import get_cursor


class MovementRepository:
    @staticmethod
    def recent_for_product(product_id: int, limit: int = 10) -> list[dict]:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT id, type, quantity, reference, notes,
                       to_char(created_at, 'YYYY-MM-DD HH24:MI') AS created_at
                FROM movements WHERE product_id = %s
                ORDER BY created_at DESC LIMIT %s
                """,
                (product_id, limit),
            )
            return list(cur.fetchall())

    @staticmethod
    def daily_totals(days: int = 14) -> list[dict]:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT date_trunc('day', created_at)::date AS day,
                       COALESCE(SUM(quantity), 0) AS total
                FROM movements
                WHERE created_at >= %s
                GROUP BY day ORDER BY day
                """,
                (date.today() - timedelta(days=days - 1),),
            )
            return list(cur.fetchall())

    @staticmethod
    def daily_for_product(product_id: int, days: int = 90) -> list[dict]:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT date_trunc('day', created_at)::date AS day,
                       COALESCE(SUM(quantity), 0) AS total
                FROM movements
                WHERE created_at >= %s AND product_id = %s
                GROUP BY day ORDER BY day
                """,
                (date.today() - timedelta(days=days - 1), product_id),
            )
            return list(cur.fetchall())

    @staticmethod
    def units_today() -> int:
        with get_cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(quantity), 0) AS units FROM movements WHERE created_at::date = %s",
                (date.today(),),
            )
            return int(cur.fetchone()["units"] or 0)

    @staticmethod
    def record(product_id: int, sku: str, mtype: str, quantity: int,
               reference: str | None = None, notes: str | None = None,
               user_id: int | None = None) -> int:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO movements (product_id, sku, type, quantity, reference, notes, user_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (product_id, sku, mtype, quantity, reference, notes, user_id),
            )
            return cur.fetchone()["id"]
