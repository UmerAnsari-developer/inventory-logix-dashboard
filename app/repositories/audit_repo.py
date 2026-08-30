"""Audit log repository via stored procedures."""
from __future__ import annotations

import json as _json

from ..database import get_cursor


class AuditRepository:
    @staticmethod
    def record(user_id: int | None, action: str, *, target_type: str | None = None,
               target_id: int | None = None, detail: dict | None = None,
               ip_address: str | None = None) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "SELECT sp_audit_record(%s, %s, %s, %s, %s, %s)",
                (
                    user_id, action, target_type, target_id,
                    _json.dumps(detail or {}), ip_address,
                ),
            )

    @staticmethod
    def recent(limit: int = 50) -> list[dict]:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_audit_recent(%s)", (limit,))
            return list(cur.fetchall())

    @staticmethod
    def count_last_hours(hours: int = 24) -> int:
        with get_cursor() as cur:
            cur.execute("SELECT sp_audit_count_last_hours(%s)", (hours,))
            return int(cur.fetchone()["sp_audit_count_last_hours"] or 0)
