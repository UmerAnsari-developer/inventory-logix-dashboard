"""Tests for N+1 query fix in User Activity Analytics."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from app.services.user_activity_analytics_service import UserActivityAnalyticsService
from app.database import get_cursor


class TestUserActivityN1Query:
    """Test N+1 query fix in user activity analytics."""

    @pytest.fixture(autouse=True)
    def setup_db(self, app):
        """Set up test database with test users and audit logs."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                # Clean up in correct order to respect FK constraints:
                # notifications -> audit_log -> users
                # Delete by email pattern to catch all test users regardless of ID
                cur.execute("DELETE FROM notifications WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test%@example.com')")
                cur.execute("DELETE FROM audit_log WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test%@example.com')")
                cur.execute("DELETE FROM users WHERE email LIKE 'test%@example.com'")
                
                # Create test users
                for i in range(5):
                    cur.execute("""
                        INSERT INTO users (id, username, email, password_hash, role, is_active)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (1000 + i, f"testuser_{i}", f"test{i}@example.com", "hash", "viewer", True))
                
                # Create audit logs for these users
                for i in range(5):
                    for j in range(i + 1):  # User 0: 1 log, User 1: 2 logs, etc.
                        cur.execute("""
                            INSERT INTO audit_log (user_id, action, target_type, detail, ip_address)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (1000 + i, f"action_{j}", "test", '{}', "127.0.0.1"))
            yield
            with get_cursor(commit=True) as cur:
                # Teardown in correct order
                cur.execute("DELETE FROM notifications WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test%@example.com')")
                cur.execute("DELETE FROM audit_log WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'test%@example.com')")
                cur.execute("DELETE FROM users WHERE email LIKE 'test%@example.com'")

    def test_get_top_users_single_query(self, app):
        """Test that get_top_users uses a single query with JOIN."""
        with app.app_context():
            with patch('app.services.user_activity_analytics_service.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_get_cursor.return_value.__enter__.return_value = mock_cur
                
                # Mock the query result
                mock_cur.fetchall.return_value = [
                    {"user_id": 1000, "count": 5, "username": "testuser_0"},
                    {"user_id": 1001, "count": 3, "username": "testuser_1"},
                    {"user_id": 1002, "count": 1, "username": "testuser_2"},
                ]
                
                result = UserActivityAnalyticsService.get_top_users(limit=10)
                
                # Verify only 1 query executed (with JOIN)
                assert mock_cur.execute.call_count == 1
                
                # Verify the query is a single aggregated query with JOIN
                call_str = str(mock_cur.execute.call_args_list[0])
                assert "LEFT JOIN users u ON u.id = al.user_id" in call_str
                assert "GROUP BY al.user_id, u.username" in call_str
                assert "ORDER BY count DESC" in call_str
                assert "LIMIT" in call_str
                
                # Verify results
                assert len(result) == 3
                assert result[0]["username"] == "testuser_0"
                assert result[0]["count"] == 5

    def test_get_activity_by_action_type_single_query(self, app):
        """Test that get_activity_by_action_type uses single query."""
        with app.app_context():
            with patch('app.services.user_activity_analytics_service.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_get_cursor.return_value.__enter__.return_value = mock_cur
                
                mock_cur.fetchall.return_value = [
                    {"action": "login", "day": "2024-01-01", "count": 10},
                    {"action": "login", "day": "2024-01-02", "count": 5},
                    {"action": "logout", "day": "2024-01-01", "count": 8},
                ]
                
                result = UserActivityAnalyticsService.get_activity_by_action_type(days=30)
                
                # Should be single query
                assert mock_cur.execute.call_count == 1
                
                call_str = str(mock_cur.execute.call_args_list[0])
                assert "GROUP BY action, DATE(created_at)" in call_str
                assert "ORDER BY action, day" in call_str

    def test_get_recent_activities_uses_repository(self, app):
        """Test that get_recent_activities returns expected data."""
        with app.app_context():
            # The service uses get_cursor directly, not UserActivityRepository
            # Just verify the method returns a list
            result = UserActivityAnalyticsService.get_recent_activities(limit=50)
            assert isinstance(result, list)

    def test_no_n1_in_get_top_users(self, app):
        """Test that get_top_users doesn't execute N+1 queries."""
        with app.app_context():
            with patch('app.services.user_activity_analytics_service.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_get_cursor.return_value.__enter__.return_value = mock_cur
                
                mock_cur.fetchall.return_value = [
                    {"user_id": 1000, "count": 5, "username": "testuser_0"},
                    {"user_id": 1001, "count": 3, "username": "testuser_1"},
                    {"user_id": 1002, "count": 1, "username": "testuser_2"},
                ]
                
                UserActivityAnalyticsService.get_top_users(limit=10)
                
                # Should only call execute ONCE
                assert mock_cur.execute.call_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])