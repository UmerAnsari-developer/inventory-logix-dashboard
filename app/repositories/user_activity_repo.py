from __future__ import annotations

from ..database import get_cursor


class UserActivityRepository:
    """Repository for reading user activities from the audit log."""

    @staticmethod
    def get_activities(limit: int = 100, offset: int = 0, user_id: int | None = None,
                       action: str | None = None, start_date: str | None = None,
                       end_date: str | None = None) -> list[dict]:
        """Get user activities with optional filtering."""
        where_clauses = []
        params = []
        
        if user_id is not None:
            where_clauses.append("user_id = %s")
            params.append(user_id)
        
        action_filtered = action is not None and action != ''
        if action_filtered:
            where_clauses.append("action = %s")
            params.append(action)
        
        if start_date is not None and start_date != '':
            where_clauses.append("created_at >= %s")
            params.append(start_date)
        
        if end_date is not None and end_date != '':
            where_clauses.append("created_at < %s")
            params.append(end_date)
        
        # Exclude generic user.login rows unless explicitly filtered for them
        if not action_filtered:
            where_clauses.append("action <> %s")
            params.append('user.login')
        
        where_clause = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT a.id, a.user_id, u.username, a.action, a.target_type,
                       a.target_id, a.detail, a.ip_address, a.created_at
                FROM audit_log a
                LEFT JOIN users u ON u.id = a.user_id
                {where_clause}
                ORDER BY a.created_at DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def get_activities_count(user_id: int | None = None,
                             action: str | None = None, start_date: str | None = None,
                             end_date: str | None = None) -> int:
        """Get total count of user activities with optional filtering."""
        where_clauses = []
        params = []
        
        if user_id is not None:
            where_clauses.append("user_id = %s")
            params.append(user_id)
        
        action_filtered = action is not None and action != ''
        if action_filtered:
            where_clauses.append("action = %s")
            params.append(action)
        
        if start_date is not None and start_date != '':
            where_clauses.append("created_at >= %s")
            params.append(start_date)
        
        if end_date is not None and end_date != '':
            where_clauses.append("created_at < %s")
            params.append(end_date)
        
        # Exclude generic user.login rows unless explicitly filtered for them
        if not action_filtered:
            where_clauses.append("action <> %s")
            params.append('user.login')
        
        where_clause = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*) as cnt
                FROM audit_log
                {where_clause}
                """,
                (*params,),
            )
            row = cur.fetchone()
            return row["cnt"] if row else 0

    @staticmethod
    def get_recent_activities(limit: int = 50) -> list[dict]:
        """Get recent user activities."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, action, target_type, target_id, detail,
                       ip_address, created_at
                FROM audit_log
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def get_activities_by_user(user_id: int, limit: int = 100) -> list[dict]:
        """Get activities for a specific user."""
        return UserActivityRepository.get_activities(user_id=user_id, limit=limit)