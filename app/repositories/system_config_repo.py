"""System configuration override repository."""
from __future__ import annotations

from ..database import get_cursor


class SystemConfigRepository:
    """Persistence for system configuration overrides."""

    @staticmethod
    def get_all() -> list[dict]:
        """Get all overrides as a list of dictionaries."""
        with get_cursor() as cur:
            cur.execute(
                "SELECT id, key, value, description, updated_at, updated_by FROM system_config_overrides ORDER BY key"
            )
            rows = cur.fetchall()
            # Convert datetime objects to string for JSON serialization if needed, but we'll keep them as is for now
            return [dict(row) for row in rows]

    @staticmethod
    def get_by_key(key: str) -> dict | None:
        """Get an override by key as a dictionary."""
        with get_cursor() as cur:
            cur.execute(
                "SELECT id, key, value, description, updated_at, updated_by FROM system_config_overrides WHERE key = %s",
                (key,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    @staticmethod
    def set_override(key: str, value: str, description: str | None = None, updated_by: int = None) -> None:
        """Set an override (insert or update)."""
        with get_cursor(commit=True) as cur:
            # Try to update first
            cur.execute(
                """
                UPDATE system_config_overrides
                SET value = %s, description = %s, updated_at = NOW(), updated_by = %s
                WHERE key = %s
                """,
                (value, description, updated_by, key),
            )
            if cur.rowcount == 0:
                # Insert if not exists
                cur.execute(
                    """
                    INSERT INTO system_config_overrides (key, value, description, updated_by)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (key, value, description, updated_by),
                )

    @staticmethod
    def delete_override(key: str) -> None:
        """Delete an override by key."""
        with get_cursor(commit=True) as cur:
            cur.execute(
                "DELETE FROM system_config_overrides WHERE key = %s",
                (key,),
            )