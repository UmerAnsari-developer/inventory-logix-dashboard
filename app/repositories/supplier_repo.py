"""Supplier repository via stored procedures."""
from __future__ import annotations

from ..database import get_cursor
from ..utils import format_money_display


class SupplierRepository:
    @staticmethod
    def list_all() -> list[dict]:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_supplier_list_all()")
            rows = list(cur.fetchall())
        for row in rows:
            row["spend_display"] = format_money_display(row.get("spend_amount"))
            row["lead_text"] = f"{row.get('lead_days') or 0} days"
        return rows

    @staticmethod
    def find(supplier_id: int) -> dict | None:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_supplier_find(%s)", (supplier_id,))
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
                "SELECT sp_supplier_create(%s,%s,%s,%s,%s,%s,%s)",
                (
                    payload["name"], initials, payload.get("location"),
                    int(payload.get("lead_days") or 0),
                    float(payload.get("spend_amount") or 0),
                    float(payload.get("reliability") or 90.0),
                    payload.get("tone") or "amber",
                ),
            )
            return cur.fetchone()["sp_supplier_create"]

    @staticmethod
    def update(supplier_id: int, payload: dict) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "SELECT sp_supplier_update(%s,%s,%s,%s,%s,%s,%s)",
                (
                    supplier_id,
                    payload["name"], payload.get("location"),
                    int(payload.get("lead_days") or 0),
                    float(payload.get("spend_amount") or 0),
                    float(payload.get("reliability") or 90.0),
                    payload.get("tone") or "amber",
                ),
            )

    @staticmethod
    def delete(supplier_id: int) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_supplier_delete(%s)", (supplier_id,))
