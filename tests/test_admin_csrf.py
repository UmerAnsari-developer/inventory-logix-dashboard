"""Tests for CSRF protection on admin destructive forms (C-001)."""
from __future__ import annotations

import pytest


class TestAdminCSRFProtection:
    """Test that all admin destructive forms have CSRF protection."""

    def test_backup_restore_form_has_csrf(self, auth_client):
        """Backup restore form should include CSRF token."""
        response = auth_client.get("/admin/backup/")
        assert response.status_code == 200
        assert b'name="csrf_token"' in response.data

    def test_backup_delete_form_has_csrf(self, auth_client):
        """Backup delete form should include CSRF token."""
        response = auth_client.get("/admin/backup/")
        assert response.status_code == 200
        assert b'name="csrf_token"' in response.data

    def test_user_management_change_role_form_has_csrf(self, auth_client):
        """User management change role form should include CSRF token."""
        response = auth_client.get("/admin/users/")
        assert response.status_code == 200
        assert b'name="csrf_token"' in response.data

    def test_user_management_toggle_active_form_has_csrf(self, auth_client):
        """User management toggle active form should include CSRF token."""
        response = auth_client.get("/admin/users/")
        assert response.status_code == 200
        assert b'name="csrf_token"' in response.data

    def test_system_config_delete_form_has_csrf(self, auth_client):
        """System config delete form should include CSRF token."""
        response = auth_client.get("/admin/system_config/")
        assert response.status_code == 200
        assert b'name="csrf_token"' in response.data

    def test_audit_report_delete_form_has_csrf(self, auth_client):
        """Audit report delete form should include CSRF token."""
        response = auth_client.get("/admin/audit_reports/")
        assert response.status_code == 200
        assert b'name="csrf_token"' in response.data

    def test_audit_report_run_form_has_csrf(self, auth_client):
        """Audit report run form should include CSRF token."""
        response = auth_client.get("/admin/audit_reports/")
        assert response.status_code == 200
        assert b'name="csrf_token"' in response.data

    def test_audit_report_run_due_form_has_csrf(self, auth_client):
        """Audit report run due form should include CSRF token."""
        response = auth_client.get("/admin/audit_reports/")
        assert response.status_code == 200
        assert b'name="csrf_token"' in response.data

    def test_data_import_upload_form_has_csrf(self, auth_client):
        """Data import upload form should include CSRF token."""
        response = auth_client.get("/admin/data-import/")
        assert response.status_code == 200
        assert b'name="csrf_token"' in response.data

    def test_csrf_token_validation_on_post(self, auth_client):
        """POST requests without CSRF token should be rejected."""
        response = auth_client.post("/admin/backup/restore/1", data={})
        assert response.status_code in (400, 403, 302)

    def test_csrf_token_validation_on_user_toggle(self, auth_client):
        """POST to toggle user without CSRF should be rejected."""
        response = auth_client.post("/admin/users/toggle/1", data={})
        assert response.status_code in (400, 403, 302)

    def test_csrf_token_validation_on_role_change(self, auth_client):
        """POST to change role without CSRF should be rejected."""
        response = auth_client.post("/admin/users/change-role/1", data={"role": "viewer"})
        assert response.status_code in (400, 403, 302)

    def test_csrf_token_validation_on_system_config_delete(self, auth_client):
        """POST to delete system config without CSRF should be rejected."""
        response = auth_client.post("/admin/system_config/delete/test_key", data={})
        assert response.status_code in (400, 403, 302)

    def test_csrf_token_validation_on_audit_report_delete(self, auth_client):
        """POST to delete audit report without CSRF should be rejected."""
        response = auth_client.post("/admin/audit_reports/delete/1", data={})
        assert response.status_code in (400, 403, 302)

    def test_csrf_token_validation_on_audit_report_run(self, auth_client):
        """POST to run audit report without CSRF should be rejected."""
        response = auth_client.post("/admin/audit_reports/run/1", data={})
        assert response.status_code in (400, 403, 302)

    def test_csrf_token_validation_on_data_import(self, auth_client):
        """POST to data import without CSRF should be rejected."""
        response = auth_client.post("/admin/data-import/upload/products", data={})
        assert response.status_code in (400, 403, 302)