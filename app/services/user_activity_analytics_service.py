"""User activity analytics service with N+1 query fix."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

from ..repositories import UserActivityRepository
from ..database import get_cursor


class UserActivityAnalyticsService:
    """Service for analyzing user activity data."""

    @staticmethod
    def get_activity_counts_by_day(days: int = 30) -> List[Dict[str, Any]]:
        """Get activity counts per day for the last N days."""
        end_date = date.today()
        start_date = end_date - timedelta(days=days-1)
        
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT DATE(created_at) AS day, COUNT(*) AS count
                FROM audit_log
                WHERE created_at >= %s AND created_at < %s
                GROUP BY DATE(created_at)
                ORDER BY day
                """,
                (start_date, end_date + timedelta(days=1)),
            )
            rows = cur.fetchall()
            # Fill in missing days with zero counts
            result = []
            current = start_date
            row_dict = {row["day"]: row["count"] for row in rows}
            while current <= end_date:
                result.append({
                    "day": current.isoformat(),
                    "count": row_dict.get(current, 0)
                })
                current += timedelta(days=1)
            return result

    @staticmethod
    def get_top_users(limit: int = 10) -> List[Dict[str, Any]]:
        """Get top users by activity count - single query with JOIN."""
        with get_cursor() as cur:
            # Single query with JOIN to avoid N+1
            cur.execute(
                """
                SELECT al.user_id, COUNT(*) AS count, u.username
                FROM audit_log al
                LEFT JOIN users u ON u.id = al.user_id
                WHERE al.user_id IS NOT NULL
                GROUP BY al.user_id, u.username
                ORDER BY count DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            result = []
            for row in rows:
                result.append({
                    "user_id": row["user_id"],
                    "username": row["username"] or f"User {row['user_id']}",
                    "count": row["count"]
                })
            return result

    @staticmethod
    def get_top_actions(limit: int = 10) -> List[Dict[str, Any]]:
        """Get top actions by count."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT action, COUNT(*) AS count
                FROM audit_log
                GROUP BY action
                ORDER BY count DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def get_activity_by_action_type(days: int = 30) -> List[Dict[str, Any]]:
        """Get activity counts by action type for the last N days."""
        end_date = date.today()
        start_date = end_date - timedelta(days=days-1)
        
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT action, DATE(created_at) AS day, COUNT(*) AS count
                FROM audit_log
                WHERE created_at >= %s AND created_at < %s
                GROUP BY action, DATE(created_at)
                ORDER BY action, day
                """,
                (start_date, end_date + timedelta(days=1)),
            )
            return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def get_recent_activities(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Get recent user activities with pagination."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, action, target_type, target_id, detail,
                       ip_address, created_at
                FROM audit_log
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def get_recent_activities_count() -> int:
        """Get total count of recent activities."""
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM audit_log")
            row = cur.fetchone()
            return row["cnt"] if row else 0