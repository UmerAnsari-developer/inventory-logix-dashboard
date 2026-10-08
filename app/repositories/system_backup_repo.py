"""System backup repository."""
from __future__ import annotations

from ..database import get_cursor


class SystemBackupRepository:
    """Persistence for system backups."""

    @staticmethod
    def add(
        backup_name: str, 
        backup_type: str, 
        file_path: str, 
        size: int, 
        status: str, 
        created_by: int,
        encrypted: bool = False,
        encryption_key_id: str | None = None,
        checksum: str | None = None
    ) -> int:
        """Add a new backup record and return the ID."""
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO system_backups 
                (backup_name, backup_type, file_path, size, status, created_by, encrypted, encryption_key_id, checksum)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (backup_name, backup_type, file_path, size, status, created_by, encrypted, encryption_key_id, checksum),
            )
            return cur.fetchone()["id"]

    @staticmethod
    def get_by_id(backup_id: int) -> dict | None:
        """Get a backup by ID."""
        with get_cursor() as cur:
            cur.execute(
                "SELECT * FROM system_backups WHERE id = %s AND deleted_at IS NULL",
                (backup_id,),
            )
            return cur.fetchone()

    @staticmethod
    def list_all(limit: int = 100, offset: int = 0, include_deleted: bool = False) -> list[dict]:
        """List all backups, most recent first."""
        where_clause = "" if include_deleted else "WHERE deleted_at IS NULL"
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM system_backups
                {where_clause}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            return cur.fetchall()

    @staticmethod
    def count_all(include_deleted: bool = False) -> int:
        """Count all backups."""
        where_clause = "" if include_deleted else "WHERE deleted_at IS NULL"
        with get_cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) as cnt FROM system_backups {where_clause}"
            )
            row = cur.fetchone()
            return row["cnt"] if row else 0

    @staticmethod
    def delete_by_id(backup_id: int) -> None:
        """Soft delete a backup record using stored procedure."""
        with get_cursor(commit=True) as cur:
            cur.execute(
                "SELECT sp_system_backup_delete(%s)",
                (backup_id,),
            )