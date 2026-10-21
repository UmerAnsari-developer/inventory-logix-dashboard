"""Tests for config validation allowlist (M-003 + R-003)."""
from __future__ import annotations

import pytest


class TestConfigValidationAllowlist:
    """Test that only allowed config keys can be set via admin."""

    def test_system_config_rejects_unknown_keys(self, auth_client):
        """System config should reject keys not in allowlist."""
        response = auth_client.post(
            "/admin/system_config/create",
            data={
                "key": "UNKNOWN_DANGEROUS_KEY",
                "value": "malicious_value",
                "csrf_token": "test"
            },
            follow_redirects=True
        )
        # Should be rejected with error
        assert response.status_code == 200
        assert b"error" in response.data.lower() or b"not allowed" in response.data.lower() or b"invalid" in response.data.lower()

    def test_system_config_allows_known_keys(self, auth_client):
        """System config should allow keys in allowlist."""
        # DB-063: dead keys (AI_FORECAST_ENABLED, ANOMALY_DETECTION_ENABLED,
        # DARK_MODE_ENABLED, SECURITY_HEADERS_ENABLED) were removed from the
        # allowlist — they were never read by application code.
        allowed_keys = [
            "RUN_ETL_ON_STARTUP",
        ]
        
        for key in allowed_keys:
            response = auth_client.post(
                "/admin/system_config/create",
                data={
                    "key": key,
                    "value": "true",
                    "csrf_token": "test"
                },
                follow_redirects=True
            )
            # Should succeed (or at least not reject for being unknown)
            # May fail for other reasons (duplicate, etc.) but not "unknown key"
            assert b"unknown" not in response.data.lower() or b"not allowed" not in response.data.lower()

    def test_system_config_validates_value_types(self, auth_client):
        """System config should validate value types for known keys."""
        # Boolean keys should accept true/false
        response = auth_client.post(
            "/admin/system_config/create",
            data={
                "key": "RUN_ETL_ON_STARTUP",
                "value": "not_a_boolean",
                "csrf_token": "test"
            },
            follow_redirects=True
        )
        # Should reject invalid boolean
        assert response.status_code == 200
        assert b"error" in response.data.lower() or b"invalid" in response.data.lower()

    def test_system_config_service_has_allowlist(self):
        """SystemConfigService should have an allowlist of valid keys."""
        from app.services.system_config_service import SystemConfigService
        
        assert hasattr(SystemConfigService, 'ALLOWED_KEYS')
        assert isinstance(SystemConfigService.ALLOWED_KEYS, (list, set, dict))
        assert len(SystemConfigService.ALLOWED_KEYS) > 0

    def test_system_config_service_validates_key(self):
        """SystemConfigService should validate keys against allowlist."""
        from app.services.system_config_service import SystemConfigService
        
        assert hasattr(SystemConfigService, 'validate_key')
        # Should raise for unknown keys
        with pytest.raises(ValueError):
            SystemConfigService.validate_key("UNKNOWN_KEY")
        
        # Should not raise for known keys
        SystemConfigService.validate_key("RUN_ETL_ON_STARTUP")

    def test_system_config_service_validates_value(self):
        """SystemConfigService should validate values for keys."""
        from app.services.system_config_service import SystemConfigService
        
        assert hasattr(SystemConfigService, 'validate_value')
        # Should validate boolean
        assert SystemConfigService.validate_value("RUN_ETL_ON_STARTUP", "true") is True
        assert SystemConfigService.validate_value("RUN_ETL_ON_STARTUP", "false") is True
        
        # Should reject invalid boolean
        with pytest.raises(ValueError):
            SystemConfigService.validate_value("RUN_ETL_ON_STARTUP", "not_bool")