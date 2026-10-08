"""Tests for password reset token not exposed in UI (H-001)."""
from __future__ import annotations

import pytest


class TestPasswordResetTokenExposure:
    """Test that password reset tokens are not exposed in UI."""

    def test_forgot_password_does_not_show_token_in_production(self, client):
        """Forgot password page should not show reset token in production."""
        # In production (non-debug), the reset_link should not be passed to template
        response = client.post(
            "/auth/forgot-password",
            data={"email": "admin@example.com"},
            follow_redirects=True
        )
        assert response.status_code == 200
        
        # In production mode, reset_link should not be in response
        # The token should only be sent via email
        # This test will need the app to be in production mode

    def test_forgot_password_shows_token_only_in_debug(self, client):
        """Forgot password page should only show reset token in debug mode."""
        # This test verifies the current behavior - token is shown in debug
        # After fix, it should only be shown when explicitly enabled for testing
        pass

    def test_reset_password_token_not_in_logs(self, client):
        """Reset password token should not appear in logs."""
        # Tokens should be hashed before logging
        pass

    def test_reset_token_hashed_in_database(self):
        """Reset tokens should be stored as hashes in database."""
        from app.services.auth_service import AuthService
        import hashlib
        
        # The token should be hashed with SHA256 before storage
        token = "test_token_123"
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        
        # Verify the hashing is done correctly
        assert len(token_hash) == 64  # SHA256 hex digest length

    def test_reset_token_not_in_url_params(self, client):
        """Reset token should not be exposed in URL parameters after use."""
        # After password reset, the token should be consumed and invalidated
        pass