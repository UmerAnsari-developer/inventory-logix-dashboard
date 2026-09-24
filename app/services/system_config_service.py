"""System configuration override service."""
from __future__ import annotations

from flask import g
from flask_login import current_user

from ..database import get_cursor
from ..repositories import SystemConfigRepository


class SystemConfigService:
    """Service for managing system configuration overrides."""

    @staticmethod
    def get_all() -> list[dict]:
        """Get all overrides as a list of dictionaries."""
        return SystemConfigRepository.get_all()

    @staticmethod
    def get_by_key(key: str) -> dict | None:
        """Get an override by key as a dictionary."""
        return SystemConfigRepository.get_by_key(key)

    @staticmethod
    def set_override(key: str, value: str, description: str | None = None) -> None:
        """Set an override for the current user."""
        if not current_user.is_authenticated:
            raise ValueError("Authentication required")
        SystemConfigRepository.set_override(
            key=key,
            value=value,
            description=description,
            updated_by=current_user.id
        )

    @staticmethod
    def delete_override(key: str) -> None:
        """Delete an override."""
        if not current_user.is_authenticated:
            raise ValueError("Authentication required")
        SystemConfigRepository.delete_override(key)