"""Tests for notification center pagination."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from app.services.nnotification_center_service import NotificationCenterService
from app.repositories import NotificationRepository
from app.database import get_cursor


class TestNotificationPagination:
    """Test notification center pagination."""

    @pytest.fixture(autouse=True)
    def setup_db(self, app):
        """Set up test database with notifications."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                # Clean up
                cur.execute("DELETE FROM notifications WHERE user_id = 9999")
                cur.execute("DELETE FROM users WHERE id = 9999")
                
                # Create test user
                cur.execute("""
                    INSERT INTO users (id, username, email, password_hash, role, is_active)
                    VALUES (9999, 'test_notif_user', 'notif@test.com', 'hash', 'viewer', True)
                """)
                
                # Create test notifications
                for i in range(25):
                    cur.execute("""
                        INSERT INTO notifications (user_id, title, message, icon, link, is_read)
                        VALUES (9999, %s, %s, %s, %s, %s)
                    """, (f"Notification {i}", f"Message {i}", "&#9675;", "/test", i % 2 == 0))
            yield
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM notifications WHERE user_id = 9999")
                cur.execute("DELETE FROM users WHERE id = 9999")

    def test_list_notifications_supports_pagination(self, app):
        """Test that list_notifications supports limit and offset."""
        with app.app_context():
            with patch('app.services.nnotification_center_service.current_user') as mock_user:
                mock_user.is_authenticated = True
                mock_user.id = 9999
                
                # Test first page
                result = NotificationCenterService.list_notifications(limit=10, offset=0)
                assert len(result) == 10
                
                # Test second page
                result = NotificationCenterService.list_notifications(limit=10, offset=10)
                assert len(result) == 10
                
                # Test third page (partial)
                result = NotificationCenterService.list_notifications(limit=10, offset=20)
                assert len(result) == 5

    def test_list_notifications_orders_by_created_at_desc(self, app):
        """Test that notifications are ordered by created_at DESC."""
        with app.app_context():
            with patch('app.services.nnotification_center_service.current_user') as mock_user:
                mock_user.is_authenticated = True
                mock_user.id = 9999
                
                result = NotificationCenterService.list_notifications(limit=5, offset=0)
                
                # Should be ordered newest first
                for i in range(len(result) - 1):
                    assert result[i]["created_at"] >= result[i + 1]["created_at"]

    def test_repository_supports_pagination(self, app):
        """Test that NotificationRepository.list_for_user supports pagination."""
        with app.app_context():
            # Test the repository method directly
            result = NotificationRepository.list_for_user(9999, limit=10, offset=0)
            assert len(result) == 10
            
            result = NotificationRepository.list_for_user(9999, limit=10, offset=10)
            assert len(result) == 10
            
            result = NotificationRepository.list_for_user(9999, limit=10, offset=20)
            assert len(result) == 5

    def test_get_unread_count_works_with_pagination(self, app):
        """Test that get_unread_count works correctly."""
        with app.app_context():
            with patch('app.services.nnotification_center_service.current_user') as mock_user:
                mock_user.is_authenticated = True
                mock_user.id = 9999
                
                count = NotificationCenterService.get_unread_count()
                # We created 25 notifications, half unread (12 or 13)
                assert count >= 12

    def test_pagination_in_template_context(self, app):
        """Test that pagination info is available for template."""
        with app.app_context():
            with patch('app.services.nnotification_center_service.current_user') as mock_user:
                mock_user.is_authenticated = True
                mock_user.id = 9999
                
                # Get total count
                total = NotificationRepository.count_all(9999)
                assert total == 25
                
                # Calculate pages
                page_size = 10
                total_pages = (total + page_size - 1) // page_size
                assert total_pages == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])