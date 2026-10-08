"""Tests for centralized audit decorator."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from functools import wraps

from flask import Flask, request
from flask_login import login_user

from app.security.audit import audit_action, audit_admin_action
from app.repositories import AuditRepository
from app.database import get_cursor
from app.repositories import UserRepository


@pytest.fixture
def admin_user_id(app):
    """Get the admin user ID dynamically (avoids hardcoded ID=1)."""
    with app.app_context():
        admin = UserRepository.find_by_username("admin")
        assert admin is not None, "admin user must exist"
        return admin.id


@pytest.fixture
def admin_user(app, admin_user_id):
    """Get the admin user object for login_user."""
    with app.app_context():
        return UserRepository.find_by_id(admin_user_id)


class TestAuditDecorator:
    """Test centralized audit decorator for admin routes.

    Uses the session-scoped ``app`` fixture from conftest: the decorator
    touches the DB (AuditRepository) and flask-login, so a bare local Flask
    app cannot serve these tests — ``get_cursor`` needs the real app's
    ``psycopg2_params`` and ``patch(current_user)`` needs its login_manager.
    """

    def test_audit_action_decorator_exists(self):
        """Test that audit_action decorator exists and is callable."""
        assert callable(audit_action)
        assert callable(audit_admin_action)

    def test_audit_action_logs_on_success(self, app, admin_user):
        """Test that audit_action logs successful actions."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM audit_log")
            
            @audit_action("test.action", target_type="test")
            def test_func():
                return "success"
            
            # Log in the admin user
            with app.test_request_context():
                login_user(admin_user)
                result = test_func()
            
            assert result == "success"
            
            # Check audit log
            with get_cursor() as cur:
                cur.execute("""
                    SELECT * FROM audit_log 
                    WHERE action = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """, ("test.action",))
                row = cur.fetchone()
                assert row is not None
                assert row["action"] == "test.action"
                assert row["target_type"] == "test"
                assert row["user_id"] == admin_user.id
                assert row["ip_address"] == "127.0.0.1"

    def test_audit_action_logs_on_exception(self, app, admin_user):
        """Test that audit_action logs failed actions."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM audit_log")
            
            @audit_action("test.action.fail", target_type="test")
            def test_func():
                raise ValueError("Test error")
            
            with app.test_request_context():
                login_user(admin_user)
                with pytest.raises(ValueError):
                    test_func()
            
            # Check audit log for failure
            with get_cursor() as cur:
                cur.execute("""
                    SELECT * FROM audit_log 
                    WHERE action = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """, ("test.action.fail",))
                row = cur.fetchone()
                assert row is not None
                assert row["action"] == "test.action.fail"
                assert row["detail"]["error"] == "Test error"
                assert row["detail"]["success"] is False

    def test_audit_admin_action_requires_admin(self, app):
        """Test that audit_admin_action checks admin role."""
        with app.app_context():
            @audit_admin_action("admin.action", target_type="admin")
            def admin_func():
                return "admin success"
            
            # Create a viewer user and log them in
            with app.app_context():
                from app.repositories import UserRepository
                viewer = UserRepository.find_by_username("viewer")
                assert viewer is not None
            
            with app.test_request_context():
                login_user(viewer)
                with pytest.raises(PermissionError):
                    admin_func()

    def test_audit_admin_action_allows_admin(self, app, admin_user):
        """Test that audit_admin_action allows admin users."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM audit_log")
            
            @audit_admin_action("admin.action", target_type="admin")
            def admin_func():
                return "admin success"
            
            with app.test_request_context():
                login_user(admin_user)
                result = admin_func()
            
            assert result == "admin success"
            
            # Check audit log
            with get_cursor() as cur:
                cur.execute("""
                    SELECT * FROM audit_log 
                    WHERE action = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """, ("admin.action",))
                row = cur.fetchone()
                assert row is not None
                assert row["user_id"] == admin_user.id

    def test_audit_decorator_with_target_id(self, app, admin_user):
        """Test audit decorator with dynamic target_id from function args."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM audit_log")
            
            @audit_action("user.update", target_type="user", target_id_arg="user_id")
            def update_user(user_id: int, name: str):
                return {"id": user_id, "name": name}
            
            with app.test_request_context():
                login_user(admin_user)
                result = update_user(42, "New Name")
            
            assert result["id"] == 42
            
            # Check audit log has target_id
            with get_cursor() as cur:
                cur.execute("""
                    SELECT * FROM audit_log 
                    WHERE action = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """, ("user.update",))
                row = cur.fetchone()
                assert row is not None
                assert row["target_id"] == 42

    def test_audit_decorator_with_detail_func(self, app, admin_user):
        """Test audit decorator with custom detail function."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM audit_log")
            
            def make_detail(result, *args, **kwargs):
                return {"custom": "detail", "result_keys": list(result.keys()) if isinstance(result, dict) else []}
            
            @audit_action("custom.detail", target_type="custom", detail_func=make_detail)
            def custom_func():
                return {"a": 1, "b": 2}
            
            with app.test_request_context():
                login_user(admin_user)
                result = custom_func()
            
            # Check audit log has custom detail
            with get_cursor() as cur:
                cur.execute("""
                    SELECT detail FROM audit_log 
                    WHERE action = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """, ("custom.detail",))
                row = cur.fetchone()
                assert row is not None
                detail = row["detail"]
                assert detail["custom"] == "detail"
                assert "a" in detail["result_keys"]
                assert "b" in detail["result_keys"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])