"""Audit log repository."""
from __future__ import annotations

from datetime import date, timedelta

from ..database import get_cursor


class AuditRepository:
    @staticmethod
    def record(user_id: int | None, action: str, *, target_type: str | None = None,
               target_id: int | None = None, detail: dict | None = None,
               ip_address: str | None = None) -> None:
        import json as _json
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO audit_log (user_id, action, target_type, target_id, detail, ip_address)
                VALUES (%s,%s,%s,%s,%s,%s)
                """,
                (
                    user_id, action, target_type, target_id,
                    _json.dumps(detail or {}), ip_address,
                ),
            )

    @staticmethod
    def recent(limit: int = 50) -> list[dict]:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT a.id, a.action, a.target_type, a.target_id, a.detail,
                       a.created_at, u.username
                FROM audit_log a LEFT JOIN users u ON u.id = a.user_id
                ORDER BY a.created_at DESC LIMIT %s
                """,
                (limit,),
            )
            return list(cur.fetchall())

    @staticmethod
    def count_last_hours(hours: int = 24) -> int:
        with get_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM audit_log WHERE created_at >= NOW() - INTERVAL %s",
                (f"{hours} hours",),
            )
            return int(cur.fetchone()["c"] or 0)
