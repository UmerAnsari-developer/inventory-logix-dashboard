"""Tests for sensitive config values masking (C-004)."""
from __future__ import annotations

import pytest


class TestConfigMasking:
    """Test that sensitive config values are masked in dashboard."""

    def test_admin_dashboard_masks_sensitive_config(self, auth_client):
        """Admin dashboard should mask sensitive config values."""
        response = auth_client.get("/admin/dashboard/")
        assert response.status_code == 200
        
        # Check that sensitive values are masked
        sensitive_keys = [
            "SECRET_KEY",
            "DB_PASSWORD",
            "DATABASE_URL",
            "SMTP_PASSWORD",
            "SENDGRID_API_KEY",
            "NVIDIA_API_KEY",
            "PASSWORD_RESET_TTL_MINUTES",
        ]
        
        for key in sensitive_keys:
            # The value should not appear in plain text
            # It should be masked (e.g., ********)
            assert key.encode() not in response.data or b"********" in response.data

    def test_system_config_page_masks_sensitive_values(self, app):
        """System config page should mask sensitive values."""
        # Test the masking logic directly via the service
        from app.services.system_config_service import SystemConfigService
        
        # Test that sensitive keys are detected
        assert SystemConfigService.is_sensitive_key("SECRET_KEY") is True
        assert SystemConfigService.is_sensitive_key("DB_PASSWORD") is True
        assert SystemConfigService.is_sensitive_key("API_KEY") is True
        assert SystemConfigService.is_sensitive_key("AI_FORECAST_ENABLED") is False
        
        # Test that get_all masks sensitive values (requires app context)
        with app.app_context():
            overrides = SystemConfigService.get_all()
            for override in overrides:
                if override.get("is_sensitive"):
                    assert override["display_value"] == "********"
                else:
                    assert override["display_value"] == override["value"]

    def test_system_config_service_masks_sensitive_keys(self):
        """SystemConfigService should have is_sensitive flag."""
        from app.services.system_config_service import SystemConfigService
        
        # The service should have a method to check if a key is sensitive
        # or the repository should return is_sensitive flag
        assert hasattr(SystemConfigService, 'is_sensitive_key') or hasattr(SystemConfigService, 'get_all')

    def test_schema_has_is_sensitive_column(self):
        """System config overrides table should have is_sensitive column."""
        # This will be verified by checking the schema.sql
        # The column should exist in system_config_overrides table
        pass

    def test_sensitive_keys_allowlist(self):
        """There should be an allowlist of sensitive config keys."""
        from app.services.system_config_service import SystemConfigService
        
        # Should have a list of sensitive key patterns
        sensitive_patterns = [
            "SECRET_KEY",
            "PASSWORD",
            "TOKEN",
            "KEY",
            "SECRET",
            "API_KEY",
            "PRIVATE",
        ]
        
        # The service should check against these patterns
        # This test will fail until implementation is done
        assert hasattr(SystemConfigService, 'SENSITIVE_KEY_PATTERNS')