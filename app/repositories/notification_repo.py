"""Notification repository: direct SQL queries."""
from __future__ import annotations

from ..database import get_cursor


class NotificationRepository:

    @staticmethod
    def list_for_user(user_id: int, limit: int = 20) -> list[dict]:
        with get_cursor() as cur:
            cur.execute(
                """SELECT id, title, message, icon, link, is_read, created_at
                   FROM notifications
                   WHERE user_id = %s
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (user_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]

    @staticmethod
    def get(notification_id: int, user_id: int) -> dict | None:
        with get_cursor() as cur:
            cur.execute(
                """SELECT id, title, message, icon, link, is_read, created_at
                   FROM notifications
                   WHERE id = %s AND user_id = %s""",
                (notification_id, user_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    @staticmethod
    def mark_read(notification_id: int, user_id: int) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE notifications SET is_read = TRUE WHERE id = %s AND user_id = %s",
                (notification_id, user_id),
            )

    @staticmethod
    def mark_all_read(user_id: int) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE notifications SET is_read = TRUE WHERE user_id = %s AND is_read = FALSE",
                (user_id,),
            )

    @staticmethod
    def count_unread(user_id: int) -> int:
        with get_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM notifications WHERE user_id = %s AND is_read = FALSE",
                (user_id,),
            )
            row = cur.fetchone()
            return int(row["cnt"]) if row else 0

    @staticmethod
    def create(user_id: int, title: str, message: str, icon: str = "&#9675;", link: str | None = None) -> int:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """INSERT INTO notifications (user_id, title, message, icon, link)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (user_id, title, message, icon, link),
            )
            return cur.fetchone()["id"]

    @staticmethod
    def delete(notification_id: int, user_id: int) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "DELETE FROM notifications WHERE id = %s AND user_id = %s",
                (notification_id, user_id),
            )
