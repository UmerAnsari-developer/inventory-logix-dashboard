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
    def daily_inout(days: int = 14) -> list[dict]:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_movement_daily_inout(%s)", (days,))
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
    def record(product_id: int, mtype: str, quantity: int,
               reference: str | None = None, notes: str | None = None,
               user_id: int | None = None) -> int:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "SELECT sp_movement_record(%s, %s, %s, %s, %s, %s)",
                (product_id, mtype, quantity, reference, notes, user_id),
            )
            return cur.fetchone()["sp_movement_record"]

    @staticmethod
    def list_movements(
        type_filter: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        product_id: int | None = None,
        user_id: int | None = None,
        page: int = 1,
        per_page: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> list[dict]:
        """List movements with filters, pagination, and sorting."""
        with get_cursor() as cur:
            cur.execute(
                "SELECT * FROM sp_movement_list(%s::text[], %s::date, %s::date, %s::int, %s::int, %s::int, %s::int, %s::text, %s::text)",
                (type_filter, date_from, date_to, product_id, user_id, page, per_page, sort_by, sort_order),
            )
            return list(cur.fetchall())

    @staticmethod
    def get_movement_count(
        type_filter: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        product_id: int | None = None,
        user_id: int | None = None,
    ) -> int:
        """Get total count of movements matching filters."""
        with get_cursor() as cur:
            cur.execute(
                "SELECT sp_movement_count(%s, %s, %s, %s, %s)",
                (type_filter, date_from, date_to, product_id, user_id),
            )
            return int(cur.fetchone()["sp_movement_count"] or 0)

    @staticmethod
    def export_movements(
        type_filter: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        product_id: int | None = None,
        user_id: int | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        limit: int = 5000,
    ):
        """Export movements as CSV stream using stored procedure."""
        import io
        import csv

        with get_cursor() as cur:
            cur.execute(
                "SELECT * FROM sp_movement_export_data(%s, %s, %s, %s, %s, %s, %s, %s)",
                (type_filter, date_from, date_to, product_id, user_id, limit, sort_by, sort_order),
            )
            rows = cur.fetchall()
            if not rows:
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(["id", "type", "quantity", "reference", "notes", "created_at", "user_id", "product_name", "sku", "user_name"])
                output.seek(0)
                return output

            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
            output.seek(0)
            return output