"""User activity analytics service."""
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
                (start_date, end_date + timedelta(days=1)),  # end_date is inclusive
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
        """Get top users by activity count."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT user_id, COUNT(*) AS count
                FROM audit_log
                WHERE user_id IS NOT NULL
                GROUP BY user_id
                ORDER BY count DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            # Get usernames for the user IDs
            from ..repositories import UserRepository
            user_ids = [row["user_id"] for row in rows]
            users = UserRepository.find_by_ids(user_ids) if user_ids else []
            user_map = {user["id"]: user["username"] for user in users}
            result = []
            for row in rows:
                result.append({
                    "user_id": row["user_id"],
                    "username": user_map.get(row["user_id"], f"User {row['user_id']}"),
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
            rows = cur.fetchall()
            # We'll return a list of dicts, but for simplicity, we'll just return the raw rows
            # The caller can process them as needed.
            return [dict(row) for row in rows]

    @staticmethod
    def get_recent_activities(limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent user activities."""
        return UserActivityRepository.get_recent_activities(limit=limit)
