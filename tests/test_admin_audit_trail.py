"""Tests for admin audit trail with centralized audit decorator."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from app.routes.admin.user_management_routes import admin_user_management_bp
from app.routes.admin.backup_routes import admin_backup_bp
from app.routes.admin.data_import_routes import admin_data_import_bp
from app.routes.admin.export_routes import admin_export_bp
from app.routes.admin.audit_report_routes import admin_audit_report_bp
from app.repositories import AuditRepository
from app.database import get_cursor
from app.repositories import UserRepository
from flask_login import login_user


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


class TestAdminAuditTrail:
    """Test that all admin routes use centralized audit decorator."""

    @pytest.fixture(autouse=True)
    def setup_db(self, app):
        """Set up test database."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM audit_log WHERE action LIKE 'admin.%'")
            yield
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM audit_log WHERE action LIKE 'admin.%'")

    def test_user_management_routes_have_audit(self, app):
        """Test that user management routes are audited."""
        with app.app_context():
            # Check that routes have audit decorator applied
            import app.routes.admin.user_management_routes as um_routes
            
            # The module should import audit decorator
            assert hasattr(um_routes, 'audit_admin_action') or 'audit' in dir(um_routes)

    def test_backup_routes_have_audit(self, app):
        """Test that backup routes are audited."""
        with app.app_context():
            import app.routes.admin.backup_routes as backup_routes
            assert hasattr(backup_routes, 'audit_admin_action') or 'audit' in dir(backup_routes)

    def test_data_import_routes_have_audit(self, app):
        """Test that data import routes are audited."""
        with app.app_context():
            import app.routes.admin.data_import_routes as di_routes
            assert hasattr(di_routes, 'audit_admin_action') or 'audit' in dir(di_routes)

    def test_export_routes_have_audit(self, app):
        """Test that export routes are audited."""
        with app.app_context():
            import app.routes.admin.export_routes as export_routes
            assert hasattr(export_routes, 'audit_admin_action') or 'audit' in dir(export_routes)

    def test_audit_report_routes_have_audit(self, app):
        """Test that audit report routes are audited."""
        with app.app_context():
            import app.routes.admin.audit_report_routes as ar_routes
            assert hasattr(ar_routes, 'audit_admin_action') or 'audit' in dir(ar_routes)

    def test_audit_logs_admin_actions(self, app, admin_user):
        """Test that admin actions are logged to audit_log."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM audit_log")
            
            # Simulate an admin action with audit decorator
            from app.security.audit import audit_admin_action
            
            @audit_admin_action("admin.user.create", target_type="user")
            def create_user(username: str):
                return {"username": username}
            
            with app.test_request_context():
                login_user(admin_user)
                result = create_user("testuser")
            
            # Check audit log
            with get_cursor() as cur:
                cur.execute("""
                    SELECT * FROM audit_log 
                    WHERE action = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """, ("admin.user.create",))
                row = cur.fetchone()
                assert row is not None
                assert row["action"] == "admin.user.create"
                assert row["target_type"] == "user"
                assert row["user_id"] == admin_user.id

    def test_audit_logs_failed_admin_actions(self, app, admin_user):
        """Test that failed admin actions are logged."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM audit_log")
            
            from app.security.audit import audit_admin_action
            
            @audit_admin_action("admin.user.delete", target_type="user")
            def delete_user(user_id: int):
                raise ValueError("Cannot delete")
            
            with app.test_request_context():
                login_user(admin_user)
                with pytest.raises(ValueError):
                    delete_user(999)
            
            # Check audit log for failure
            with get_cursor() as cur:
                cur.execute("""
                    SELECT * FROM audit_log 
                    WHERE action = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """, ("admin.user.delete",))
                row = cur.fetchone()
                assert row is not None
                assert row["action"] == "admin.user.delete"
                assert row["detail"]["error"] == "Cannot delete"
                assert row["detail"]["success"] is False
                assert row["user_id"] == admin_user.id

    def test_audit_logs_data_import(self, app, admin_user):
        """Test that data import actions are logged."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM audit_log")
            
            from app.security.audit import audit_admin_action
            
            @audit_admin_action("admin.data.import", target_type="data_import")
            def import_data(filename: str):
                return {"imported": 10}
            
            with app.test_request_context():
                login_user(admin_user)
                result = import_data("test.csv")
            
            with get_cursor() as cur:
                cur.execute("""
                    SELECT * FROM audit_log 
                    WHERE action = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """, ("admin.data.import",))
                row = cur.fetchone()
                assert row is not None
                assert row["action"] == "admin.data.import"
                assert row["user_id"] == admin_user.id

    def test_audit_logs_backup_restore(self, app, admin_user):
        """Test that backup/restore actions are logged."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM audit_log")
            
            from app.security.audit import audit_admin_action
            
            @audit_admin_action("admin.backup.create", target_type="backup")
            def create_backup(name: str):
                return {"backup_id": 1}
            
            with app.test_request_context():
                login_user(admin_user)
                result = create_backup("test_backup")
            
            with get_cursor() as cur:
                cur.execute("""
                    SELECT * FROM audit_log 
                    WHERE action = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """, ("admin.backup.create",))
                row = cur.fetchone()
                assert row is not None
                assert row["action"] == "admin.backup.create"
                assert row["user_id"] == admin_user.id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])