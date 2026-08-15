"""Settings repository — per-user key/value preferences."""
from __future__ import annotations

from ..database import get_cursor


class SettingsRepository:
    """Persistence for the ``user_settings`` table."""

    @staticmethod
    def all(user_id: int) -> dict[str, str]:
        with get_cursor() as cur:
            cur.execute(
                "SELECT key, value FROM user_settings WHERE user_id = %s",
                (user_id,),
            )
            return {row["key"]: row["value"] for row in cur.fetchall()}

    @staticmethod
    def set_many(user_id: int, values: dict[str, str]) -> None:
        with get_cursor(commit=True) as cur:
            for key, value in values.items():
                cur.execute(
                    """
                    INSERT INTO user_settings (user_id, key, value)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, key)
                    DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                    """,
                    (user_id, key, value),
                )
