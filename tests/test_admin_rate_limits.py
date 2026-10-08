"""Tests for rate limiting on admin write endpoints (C-003)."""
from __future__ import annotations

import pytest


class TestAdminRateLimits:
    """Test that admin write endpoints have rate limiting."""

    def test_backup_create_rate_limited(self, auth_client):
        """Backup create endpoint should be rate limited."""
        # Make multiple rapid requests
        for i in range(35):  # Exceed typical 30/min limit
            response = auth_client.post(
                "/admin/backup/create",
                data={"backup_name": f"test{i}", "backup_type": "full", "csrf_token": "test"},
                follow_redirects=True
            )
            if response.status_code == 429:
                # Rate limited - good
                break
        else:
            # If we didn't hit rate limit, that's a test failure
            pytest.fail("Backup create endpoint not rate limited")

    def test_backup_restore_rate_limited(self, auth_client):
        """Backup restore endpoint should be rate limited."""
        for i in range(35):
            response = auth_client.post(
                "/admin/backup/restore/1",
                data={"csrf_token": "test"},
                follow_redirects=True
            )
            if response.status_code == 429:
                break
        else:
            pytest.fail("Backup restore endpoint not rate limited")

    def test_backup_delete_rate_limited(self, auth_client):
        """Backup delete endpoint should be rate limited."""
        for i in range(35):
            response = auth_client.post(
                "/admin/backup/delete/1",
                data={"csrf_token": "test"},
                follow_redirects=True
            )
            if response.status_code == 429:
                break
        else:
            pytest.fail("Backup delete endpoint not rate limited")

    def test_user_management_create_rate_limited(self, auth_client):
        """User management create endpoint should be rate limited."""
        for i in range(35):
            response = auth_client.post(
                "/admin/users/create",
                data={
                    "username": f"testuser{i}",
                    "email": f"test{i}@example.com",
                    "password": "Test@123",
                    "role": "viewer",
                    "csrf_token": "test"
                },
                follow_redirects=True
            )
            if response.status_code == 429:
                break
        else:
            pytest.fail("User management create endpoint not rate limited")

    def test_user_management_edit_rate_limited(self, auth_client):
        """User management edit endpoint should be rate limited."""
        for i in range(35):
            response = auth_client.post(
                "/admin/users/edit/2",
                data={"role": "viewer", "is_active": "on", "csrf_token": "test"},
                follow_redirects=True
            )
            if response.status_code == 429:
                break
        else:
            pytest.fail("User management edit endpoint not rate limited")

    def test_user_management_toggle_rate_limited(self, auth_client):
        """User management toggle endpoint should be rate limited."""
        for i in range(35):
            response = auth_client.post(
                "/admin/users/toggle/2",
                data={"csrf_token": "test"},
                follow_redirects=True
            )
            if response.status_code == 429:
                break
        else:
            pytest.fail("User management toggle endpoint not rate limited")

    def test_user_management_change_role_rate_limited(self, auth_client):
        """User management change role endpoint should be rate limited."""
        for i in range(35):
            response = auth_client.post(
                "/admin/users/change-role/2",
                data={"role": "viewer", "csrf_token": "test"},
                follow_redirects=True
            )
            if response.status_code == 429:
                break
        else:
            pytest.fail("User management change role endpoint not rate limited")

    def test_system_config_create_rate_limited(self, auth_client):
        """System config create endpoint should be rate limited."""
        for i in range(35):
            response = auth_client.post(
                "/admin/system_config/create",
                data={"key": f"test_key_{i}", "value": "test", "csrf_token": "test"},
                follow_redirects=True
            )
            if response.status_code == 429:
                break
        else:
            pytest.fail("System config create endpoint not rate limited")

    def test_system_config_edit_rate_limited(self, auth_client):
        """System config edit endpoint should be rate limited."""
        for i in range(35):
            response = auth_client.post(
                "/admin/system_config/edit/test_key",
                data={"value": "test", "csrf_token": "test"},
                follow_redirects=True
            )
            if response.status_code == 429:
                break
        else:
            pytest.fail("System config edit endpoint not rate limited")

    def test_system_config_delete_rate_limited(self, auth_client):
        """System config delete endpoint should be rate limited."""
        for i in range(35):
            response = auth_client.post(
                "/admin/system_config/delete/test_key",
                data={"csrf_token": "test"},
                follow_redirects=True
            )
            if response.status_code == 429:
                break
        else:
            pytest.fail("System config delete endpoint not rate limited")

    def test_data_import_upload_rate_limited(self, auth_client):
        """Data import upload endpoint should be rate limited."""
        for i in range(35):
            response = auth_client.post(
                "/admin/data-import/upload/products",
                data={"csrf_token": "test"},
                follow_redirects=True
            )
            if response.status_code == 429:
                break
        else:
            pytest.fail("Data import upload endpoint not rate limited")

    def test_audit_report_create_rate_limited(self, auth_client):
        """Audit report create endpoint should be rate limited."""
        import time
        for i in range(35):
            response = auth_client.post(
                "/admin/audit_reports/create",
                data={
                    "name": f"test_report_{i}_{int(time.time() * 1000)}",
                    "format": "CSV",
                    "frequency": "daily",
                    "next_run_time": "2025-12-31 23:59:59",
                    "csrf_token": "test"
                },
                follow_redirects=True
            )
            if response.status_code == 429:
                break
        else:
            pytest.fail("Audit report create endpoint not rate limited")

    def test_audit_report_edit_rate_limited(self, auth_client):
        """Audit report edit endpoint should be rate limited."""
        for i in range(35):
            response = auth_client.post(
                "/admin/audit_reports/edit/1",
                data={
                    "name": "test_report",
                    "format": "CSV",
                    "frequency": "daily",
                    "next_run_time": "2025-12-31 23:59:59",
                    "csrf_token": "test"
                },
                follow_redirects=True
            )
            if response.status_code == 429:
                break
        else:
            pytest.fail("Audit report edit endpoint not rate limited")

    def test_audit_report_delete_rate_limited(self, auth_client):
        """Audit report delete endpoint should be rate limited."""
        for i in range(35):
            response = auth_client.post(
                "/admin/audit_reports/delete/1",
                data={"csrf_token": "test"},
                follow_redirects=True
            )
            if response.status_code == 429:
                break
        else:
            pytest.fail("Audit report delete endpoint not rate limited")

    def test_audit_report_run_rate_limited(self, auth_client):
        """Audit report run endpoint should be rate limited."""
        for i in range(35):
            response = auth_client.post(
                "/admin/audit_reports/run/1",
                data={"csrf_token": "test"},
                follow_redirects=True
            )
            if response.status_code == 429:
                break
        else:
            pytest.fail("Audit report run endpoint not rate limited")

    def test_audit_report_run_due_rate_limited(self, auth_client):
        """Audit report run due endpoint should be rate limited."""
        for i in range(35):
            response = auth_client.post(
                "/admin/audit_reports/run_due",
                data={"csrf_token": "test"},
                follow_redirects=True
            )
            if response.status_code == 429:
                break
        else:
            pytest.fail("Audit report run due endpoint not rate limited")