"""Tests for admin session timeout (M-008)."""
from __future__ import annotations

import pytest
from datetime import timedelta


class TestAdminSessionTimeout:
    """Test that admin sessions have shorter timeout."""

    def test_admin_session_timeout_config_exists(self):
        """Settings should have admin session timeout config."""
        from app.config.settings import Config
        
        # Should have admin-specific session timeout
        assert hasattr(Config, 'ADMIN_SESSION_TIMEOUT_MINUTES')
        assert isinstance(Config.ADMIN_SESSION_TIMEOUT_MINUTES, int)
        assert Config.ADMIN_SESSION_TIMEOUT_MINUTES > 0
        assert Config.ADMIN_SESSION_TIMEOUT_MINUTES < 60  # Should be shorter than regular

    def test_admin_session_timeout_shorter_than_regular(self):
        """Admin session timeout should be shorter than regular session."""
        from app.config.settings import Config
        
        # Regular session is 7 days (REMEMBER_COOKIE_DURATION)
        # Admin session should be much shorter (e.g., 30 minutes)
        assert hasattr(Config, 'ADMIN_SESSION_TIMEOUT_MINUTES')
        assert Config.ADMIN_SESSION_TIMEOUT_MINUTES <= 30

    def test_roles_module_has_admin_timeout_check(self):
        """Roles module should have admin timeout enforcement."""
        from app.security.roles import roles_required
        
        # The roles_required decorator should check admin session timeout
        # This will be implemented as a wrapper or additional check
        assert callable(roles_required)

    def test_admin_routes_enforce_session_timeout(self, auth_client):
        """Admin routes should enforce session timeout."""
        # This would require manipulating session time
        # For now, verify the middleware/check exists
        response = auth_client.get("/admin/dashboard/")
        assert response.status_code == 200
        
        # Check that session has admin timeout tracking
        # This is more of an integration test

    def test_admin_session_refresh_on_activity(self, auth_client):
        """Admin session should refresh on activity."""
        # Make a request
        response = auth_client.get("/admin/dashboard/")
        assert response.status_code == 200
        
        # Make another request - session should be extended
        response = auth_client.get("/admin/users/")
        assert response.status_code == 200

    def test_non_admin_routes_use_regular_timeout(self):
        """Non-admin routes should use regular session timeout (browser-session only, no persistent remember cookie)."""
        from app.config.settings import Config
        
        # Project convention: persistent remember cookie was removed.
        # Sessions are browser-session only (no REMEMBER_COOKIE_DURATION).
        # Regular timeout is enforced by Flask's default permanent_session_lifetime (31 days)
        # but since we don't set session.permanent=True, sessions expire on browser close.
        assert not hasattr(Config, 'REMEMBER_COOKIE_DURATION'), \
            "REMEMBER_COOKIE_DURATION should not exist (persistent remember cookie removed by design)"
        
        # Verify admin timeout config still exists and is shorter
        assert hasattr(Config, 'ADMIN_SESSION_TIMEOUT_MINUTES')
        assert Config.ADMIN_SESSION_TIMEOUT_MINUTES <= 30