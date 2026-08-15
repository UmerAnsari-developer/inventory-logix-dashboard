"""Supplier repository."""
from __future__ import annotations

from ..database import get_cursor
from ..utils import format_money_display


class SupplierRepository:
    @staticmethod
    def list_all() -> list[dict]:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT s.*, COUNT(p.id) AS active_skus
                FROM suppliers s LEFT JOIN products p ON p.supplier_id = s.id
                GROUP BY s.id ORDER BY s.name
                """
            )
            rows = list(cur.fetchall())
        for row in rows:
            row["spend_display"] = format_money_display(row.get("spend_amount"))
            row["lead_text"] = f"{row.get('lead_days') or 0} days"
        return rows

    @staticmethod
    def find(supplier_id: int) -> dict | None:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM suppliers WHERE id = %s", (supplier_id,))
            row = cur.fetchone()
        if row:
            row["spend_display"] = format_money_display(row.get("spend_amount"))
            row["lead_text"] = f"{row.get('lead_days') or 0} days"
        return row

    @staticmethod
    def lookup() -> dict[int, dict]:
        with get_cursor() as cur:
            cur.execute("SELECT id, name, tone, lead_days FROM suppliers")
            return {row["id"]: dict(row) for row in cur.fetchall()}

    @staticmethod
    def create(payload: dict) -> int:
        initials = "".join([w[0] for w in (payload.get("name") or "").split()[:2]]).upper()[:2]
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO suppliers (name, initials, location, lead_days, spend_amount, reliability, tone)
                VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id
                """,
                (
                    payload["name"], initials, payload.get("location"),
                    int(payload.get("lead_days") or 0),
                    float(payload.get("spend_amount") or 0),
                    float(payload.get("reliability") or 90.0),
                    payload.get("tone") or "amber",
                ),
            )
            return cur.fetchone()["id"]

    @staticmethod
    def update(supplier_id: int, payload: dict) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE suppliers SET name=%s, location=%s, lead_days=%s,
                                     spend_amount=%s, reliability=%s, tone=%s
                WHERE id=%s
                """,
                (
                    payload["name"], payload.get("location"),
                    int(payload.get("lead_days") or 0),
                    float(payload.get("spend_amount") or 0),
                    float(payload.get("reliability") or 90.0),
                    payload.get("tone") or "amber",
                    supplier_id,
                ),
            )

    @staticmethod
    def delete(supplier_id: int) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute("UPDATE products SET supplier_id = NULL WHERE supplier_id = %s", (supplier_id,))
            cur.execute("DELETE FROM suppliers WHERE id = %s", (supplier_id,))
