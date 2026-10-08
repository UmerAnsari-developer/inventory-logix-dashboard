"""User activity monitoring service."""
from __future__ import annotations

from flask import g
from flask_login import current_user

from ..repositories import UserActivityRepository


class UserActivityService:
    """Service for monitoring user activity."""

    @staticmethod
    def get_activities(limit: int = 100, offset: int = 0, user_id: int | None = None,
                       action: str | None = None, start_date: str | None = None,
                       end_date: str | None = None) -> list[dict]:
        """Get user activities with optional filtering."""
        # Only allow admins and managers to view all activities
        # Regular users can only view their own activities
        if not current_user.is_authenticated:
            raise ValueError("Authentication required")
        
        if current_user.role not in ("admin", "manager"):
            # Restrict to own activities
            user_id = current_user.id
        
        return UserActivityRepository.get_activities(
            limit=limit, offset=offset, user_id=user_id,
            action=action, start_date=start_date, end_date=end_date
        )

    @staticmethod
    def get_activities_count(user_id: int | None = None,
                             action: str | None = None, start_date: str | None = None,
                             end_date: str | None = None) -> int:
        """Get total count of user activities with optional filtering."""
        if not current_user.is_authenticated:
            raise ValueError("Authentication required")
        
        if current_user.role not in ("admin", "manager"):
            # Restrict to own activities
            user_id = current_user.id
        
        return UserActivityRepository.get_activities_count(
            user_id=user_id, action=action, start_date=start_date, end_date=end_date
        )

    @staticmethod
    def get_recent_activities(limit: int = 50) -> list[dict]:
        """Get recent user activities."""
        if not current_user.is_authenticated:
            raise ValueError("Authentication required")
        
        if current_user.role not in ("admin", "manager"):
            # Restrict to own activities
            return UserActivityRepository.get_activities_by_user(current_user.id, limit=limit)
        
        return UserActivityRepository.get_recent_activities(limit=limit)

    @staticmethod
    def get_activities_by_user(user_id: int, limit: int = 100) -> list[dict]:
        """Get activities for a specific user."""
        if not current_user.is_authenticated:
            raise ValueError("Authentication required")
        
        # Only allow admins and managers to view other users' activities
        if current_user.role not in ("admin", "manager") and current_user.id != user_id:
            raise ValueError("Insufficient permissions to view other users' activities")
        
        return UserActivityRepository.get_activities_by_user(user_id, limit=limit)