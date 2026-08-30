"""Settings repository via stored procedures."""
from __future__ import annotations

from ..database import get_cursor


class SettingsRepository:
    """Persistence for ``user_settings`` via stored procedures."""

    @staticmethod
    def all(user_id: int) -> dict[str, str]:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_settings_all(%s)", (user_id,))
            return {row["key"]: row["value"] for row in cur.fetchall()}

    @staticmethod
    def set_many(user_id: int, values: dict[str, str]) -> None:
        with get_cursor(commit=True) as cur:
            for key, value in values.items():
                cur.execute("SELECT sp_settings_set_many(%s, %s, %s)", (user_id, key, value))
