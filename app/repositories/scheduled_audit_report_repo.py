"""Scheduled audit report repository with soft delete support."""
from __future__ import annotations

from ..database import get_cursor


class ScheduledAuditReportRepository:
    """Persistence for scheduled audit reports."""

    @staticmethod
    def get_by_id(report_id: int, include_deleted: bool = False) -> dict | None:
        """Get a scheduled audit report by ID."""
        where_clause = "" if include_deleted else "AND deleted_at IS NULL"
        with get_cursor() as cur:
            cur.execute(
                f"SELECT * FROM scheduled_audit_reports WHERE id = %s {where_clause}",
                (report_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    @staticmethod
    def list_all(limit: int = 100, offset: int = 0, active_only: bool = False, include_deleted: bool = False) -> list[dict]:
        """List all scheduled audit reports."""
        where_parts = []
        if not include_deleted:
            where_parts.append("deleted_at IS NULL")
        if active_only:
            where_parts.append("is_active = TRUE")
        
        where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""
        
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM scheduled_audit_reports
                {where_clause}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def count_all(active_only: bool = False, include_deleted: bool = False) -> int:
        """Count all scheduled audit reports."""
        where_parts = []
        if not include_deleted:
            where_parts.append("deleted_at IS NULL")
        if active_only:
            where_parts.append("is_active = TRUE")
        
        where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""
        
        with get_cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) as cnt FROM scheduled_audit_reports {where_clause}"
            )
            row = cur.fetchone()
            return row["cnt"] if row else 0

    @staticmethod
    def get_due_reports() -> list[dict]:
        """Get scheduled audit reports that are due to run."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM scheduled_audit_reports
                WHERE is_active = TRUE
                  AND deleted_at IS NULL
                  AND next_run_time IS NOT NULL
                  AND next_run_time <= NOW()
                ORDER BY next_run_time
                """
            )
            return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def create(name: str, description: str, format: str, frequency: str,
               parameters: dict, next_run_time: str, created_by: int) -> int:
        """Create a new scheduled audit report."""
        import json
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO scheduled_audit_reports
                (name, description, format, frequency, parameters, next_run_time, is_active, created_by, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s, %s)
                RETURNING id
                """,
                (name, description, format, frequency, json.dumps(parameters), next_run_time, created_by, created_by),
            )
            return cur.fetchone()["id"]

    @staticmethod
    def update(report_id: int, name: str, description: str, format: str, frequency: str,
               parameters: dict, next_run_time: str, updated_by: int) -> None:
        """Update a scheduled audit report."""
        import json
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE scheduled_audit_reports
                SET name = %s, description = %s, format = %s, frequency = %s,
                    parameters = %s, next_run_time = %s, updated_by = %s, updated_at = NOW()
                WHERE id = %s AND deleted_at IS NULL
                """,
                (name, description, format, frequency, json.dumps(parameters), next_run_time, updated_by, report_id),
            )

    @staticmethod
    def delete(report_id: int) -> None:
        """Soft delete a scheduled audit report."""
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE scheduled_audit_reports SET deleted_at = NOW() WHERE id = %s",
                (report_id,),
            )

    @staticmethod
    def update_last_run(report_id: int) -> None:
        """Update the last_run_time and calculate the next_run_time based on frequency."""
        from datetime import datetime, timedelta
        import json
        
        with get_cursor() as cur:
            cur.execute(
                "SELECT frequency, parameters FROM scheduled_audit_reports WHERE id = %s AND deleted_at IS NULL",
                (report_id,),
            )
            row = cur.fetchone()
            if not row:
                return
            
            frequency = row["frequency"]
            parameters = json.loads(row["parameters"]) if row["parameters"] else {}
            
            now = datetime.now()
            if frequency == "daily":
                next_run = now + timedelta(days=1)
            elif frequency == "weekly":
                next_run = now + timedelta(weeks=1)
            elif frequency == "monthly":
                next_run = now + timedelta(days=30)
            else:
                next_run = now + timedelta(days=1)
            
            cur.execute(
                """
                UPDATE scheduled_audit_reports
                SET last_run_time = %s, next_run_time = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (now, next_run, report_id),
            )