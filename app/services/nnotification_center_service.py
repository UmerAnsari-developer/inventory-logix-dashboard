"""Notification center service."""
from __future__ import annotations

from flask import g
from flask_login import current_user

from ..repositories import NotificationRepository


class NotificationCenterService:
    """Service for managing user notifications."""

    @staticmethod
    def list_notifications(limit: int = 20, offset: int = 0) -> list[dict]:
        """List notifications for the current user."""
        if not current_user.is_authenticated:
            raise ValueError("Authentication required")
        # ADM-019: repository supports offset natively — no over-fetch + slice.
        return NotificationRepository.list_for_user(current_user.id, limit=limit, offset=offset)

    @staticmethod
    def get_notification(notification_id: int) -> dict | None:
        """Get a specific notification for the current user."""
        if not current_user.is_authenticated:
            raise ValueError("Authentication required")
        return NotificationRepository.get(notification_id, current_user.id)

    @staticmethod
    def mark_read(notification_id: int) -> None:
        """Mark a notification as read."""
        if not current_user.is_authenticated:
            raise ValueError("Authentication required")
        NotificationRepository.mark_read(notification_id, current_user.id)

    @staticmethod
    def mark_all_read() -> None:
        """Mark all notifications as read for the current user."""
        if not current_user.is_authenticated:
            raise ValueError("Authentication required")
        NotificationRepository.mark_all_read(current_user.id)

    @staticmethod
    def delete_notification(notification_id: int) -> None:
        """Delete a notification."""
        if not current_user.is_authenticated:
            raise ValueError("Authentication required")
        NotificationRepository.delete(notification_id, current_user.id)

    @staticmethod
    def get_unread_count() -> int:
        """Get the count of unread notifications for the current user."""
        if not current_user.is_authenticated:
            raise ValueError("Authentication required")
        return NotificationRepository.count_unread(current_user.id)

    @staticmethod
    def create_notification(user_id: int, title: str, message: str, icon: str = "&#9675;", link: str | None = None) -> int:
        """Create a notification for a user (typically used by the system)."""
        # This method is for system use, so we don't require the current user to be authenticated
        # but we do require a user_id.
        return NotificationRepository.create(user_id, title, message, icon, link)