"""System backup repository."""
from __future__ import annotations

from ..database import get_cursor


class SystemBackupRepository:
    """Persistence for system backups."""

    @staticmethod
    def add(backup_name: str, backup_type: str, file_path: str, size: int, status: str, created_by: int) -> int:
        """Add a new backup record and return the ID."""
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO system_backups (backup_name, backup_type, file_path, size, status, created_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (backup_name, backup_type, file_path, size, status, created_by),
            )
            return cur.fetchone()["id"]

    @staticmethod
    def get_by_id(backup_id: int) -> dict | None:
        """Get a backup by ID."""
        with get_cursor() as cur:
            cur.execute(
                "SELECT * FROM system_backups WHERE id = %s",
                (backup_id,),
            )
            return cur.fetchone()

    @staticmethod
    def list_all(limit: int = 100, offset: int = 0) -> list[dict]:
        """List all backups, most recent first."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT * FROM system_backups
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            return cur.fetchall()

    @staticmethod
    def delete_by_id(backup_id: int) -> None:
        """Delete a backup record."""
        with get_cursor(commit=True) as cur:
            cur.execute(
                "DELETE FROM system_backups WHERE id = %s",
                (backup_id,),
            )