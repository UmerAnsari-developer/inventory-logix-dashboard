"""Scheduled audit report repository."""
from __future__ import annotations

from ..database import get_cursor


class ScheduledAuditReportRepository:
    """Persistence for scheduled audit reports."""

    @staticmethod
    def get_by_id(report_id: int) -> dict | None:
        """Get a scheduled audit report by ID."""
        with get_cursor() as cur:
            cur.execute(
                "SELECT * FROM scheduled_audit_reports WHERE id = %s",
                (report_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    @staticmethod
    def list_all(limit: int = 100, offset: int = 0, active_only: bool = False) -> list[dict]:
        """List all scheduled audit reports."""
        where_clause = "WHERE is_active = TRUE" if active_only else ""
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
    def get_due_reports() -> list[dict]:
        """Get scheduled audit reports that are due to run."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM scheduled_audit_reports
                WHERE is_active = TRUE
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
                (name, description, format, frequency, parameters, next_run_time, created_by, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
                WHERE id = %s
                """,
                (name, description, format, frequency, json.dumps(parameters), next_run_time, updated_by, report_id),
            )

    @staticmethod
    def delete(report_id: int) -> None:
        """Delete a scheduled audit report."""
        with get_cursor(commit=True) as cur:
            cur.execute(
                "DELETE FROM scheduled_audit_reports WHERE id = %s",
                (report_id,),
            )

    @staticmethod
    def update_last_run(report_id: int) -> None:
        """Update the last_run_time and calculate the next_run_time based on frequency."""
        from datetime import datetime, timedelta
        import json
        
        with get_cursor() as cur:
            # Get the current report
            cur.execute(
                "SELECT frequency, parameters FROM scheduled_audit_reports WHERE id = %s",
                (report_id,),
            )
            row = cur.fetchone()
            if not row:
                return
            
            frequency = row["frequency"]
            parameters = json.loads(row["parameters"]) if row["parameters"] else {}
            
            # Calculate next run time based on frequency
            now = datetime.now()
            if frequency == "daily":
                next_run = now + timedelta(days=1)
            elif frequency == "weekly":
                next_run = now + timedelta(weeks=1)
            elif frequency == "monthly":
                # Approximate month as 30 days
                next_run = now + timedelta(days=30)
            else:
                # Default to daily
                next_run = now + timedelta(days=1)
            
            # Update the report
            cur.execute(
                """
                UPDATE scheduled_audit_reports
                SET last_run_time = %s, next_run_time = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (now, next_run, report_id),
            )