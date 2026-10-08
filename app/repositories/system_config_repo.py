"""System configuration override repository with soft delete support."""
from __future__ import annotations

from ..database import get_cursor


class SystemConfigRepository:
    """Persistence for system configuration overrides."""

    @staticmethod
    def get_all(include_deleted: bool = False) -> list[dict]:
        """Get all overrides as a list of dictionaries."""
        where_clause = "" if include_deleted else "WHERE deleted_at IS NULL"
        with get_cursor() as cur:
            cur.execute(
                f"SELECT id, key, value, description, is_sensitive, updated_at, updated_by, deleted_at FROM system_config_overrides {where_clause} ORDER BY key"
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def get_by_key(key: str, include_deleted: bool = False) -> dict | None:
        """Get an override by key as a dictionary."""
        where_clause = "" if include_deleted else "AND deleted_at IS NULL"
        with get_cursor() as cur:
            cur.execute(
                f"SELECT id, key, value, description, is_sensitive, updated_at, updated_by, deleted_at FROM system_config_overrides WHERE key = %s {where_clause}",
                (key,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_by_id(config_id: int, include_deleted: bool = False) -> dict | None:
        """Get an override by ID as a dictionary."""
        where_clause = "" if include_deleted else "AND deleted_at IS NULL"
        with get_cursor() as cur:
            cur.execute(
                f"SELECT id, key, value, description, is_sensitive, updated_at, updated_by, deleted_at FROM system_config_overrides WHERE id = %s {where_clause}",
                (config_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    @staticmethod
    def list_all(limit: int = 100, offset: int = 0, include_deleted: bool = False) -> list[dict]:
        """List all overrides with pagination."""
        where_clause = "" if include_deleted else "WHERE deleted_at IS NULL"
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT id, key, value, description, is_sensitive, updated_at, updated_by, deleted_at
                FROM system_config_overrides
                {where_clause}
                ORDER BY updated_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def set_override(key: str, value: str, description: str | None = None, updated_by: int = None) -> None:
        """Set an override (insert or update)."""
        from app.services.system_config_service import SystemConfigService
        is_sensitive = SystemConfigService.is_sensitive_key(key)
        
        with get_cursor(commit=True) as cur:
            # Try to update first (including soft-deleted)
            cur.execute(
                """
                UPDATE system_config_overrides
                SET value = %s, description = %s, is_sensitive = %s, updated_at = NOW(), updated_by = %s, deleted_at = NULL
                WHERE key = %s
                """,
                (value, description, is_sensitive, updated_by, key),
            )
            if cur.rowcount == 0:
                # Insert if not exists
                cur.execute(
                    """
                    INSERT INTO system_config_overrides (key, value, description, is_sensitive, updated_by)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (key, value, description, is_sensitive, updated_by),
                )

    @staticmethod
    def delete_override(key: str) -> None:
        """Soft delete an override by key."""
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE system_config_overrides SET deleted_at = NOW() WHERE key = %s",
                (key,),
            )

    @staticmethod
    def delete_by_id(config_id: int) -> None:
        """Soft delete an override by ID."""
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE system_config_overrides SET deleted_at = NOW() WHERE id = %s",
                (config_id,),
            )