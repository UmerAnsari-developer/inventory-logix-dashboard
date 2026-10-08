"""Tests for admin soft delete functionality."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from app.repositories import SystemBackupRepository, SystemConfigRepository, ScheduledAuditReportRepository
from app.database import get_cursor
from app.repositories import UserRepository


@pytest.fixture
def admin_user_id(app):
    """Get the admin user ID dynamically (avoids hardcoded ID=1)."""
    with app.app_context():
        admin = UserRepository.find_by_username("admin")
        assert admin is not None, "admin user must exist"
        return admin.id


class TestAdminSoftDelete:
    """Test soft delete on admin tables."""

    @pytest.fixture(autouse=True)
    def setup_db(self, app):
        """Set up test database."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM system_backups WHERE backup_name LIKE 'TEST_%'")
                cur.execute("DELETE FROM system_config_overrides WHERE key LIKE 'TEST_%'")
                cur.execute("DELETE FROM scheduled_audit_reports WHERE name LIKE 'TEST_%'")
            yield
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM system_backups WHERE backup_name LIKE 'TEST_%'")
                cur.execute("DELETE FROM system_config_overrides WHERE key LIKE 'TEST_%'")
                cur.execute("DELETE FROM scheduled_audit_reports WHERE name LIKE 'TEST_%'")

    def test_system_backup_soft_delete(self, app, admin_user_id):
        """Test soft delete for system_backups."""
        with app.app_context():
            # Create backup
            with get_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO system_backups (backup_name, backup_type, file_path, size, status, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, ("TEST_Backup_1", "full", "/tmp/test.backup", 1024, "success", admin_user_id))
                backup_id = cur.fetchone()["id"]
            
            # Soft delete
            SystemBackupRepository.delete_by_id(backup_id)
            
            # Should not appear in list_all
            backups = SystemBackupRepository.list_all()
            backup_names = [b["backup_name"] for b in backups]
            assert "TEST_Backup_1" not in backup_names
            
            # get_by_id should return None
            backup = SystemBackupRepository.get_by_id(backup_id)
            assert backup is None
            
            # But record should exist with deleted_at
            with get_cursor() as cur:
                cur.execute("SELECT deleted_at FROM system_backups WHERE id = %s", (backup_id,))
                row = cur.fetchone()
                assert row is not None
                assert row["deleted_at"] is not None

    def test_system_config_soft_delete(self, app, admin_user_id):
        """Test soft delete for system_config_overrides."""
        with app.app_context():
            # Create config
            with get_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO system_config_overrides (key, value, description, is_sensitive, updated_by)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, ("TEST_CONFIG_1", "value1", "Test config", False, admin_user_id))
                config_id = cur.fetchone()["id"]
            
            # Soft delete
            SystemConfigRepository.delete_by_id(config_id)
            
            # Should not appear in list
            configs = SystemConfigRepository.list_all()
            config_keys = [c["key"] for c in configs]
            assert "TEST_CONFIG_1" not in config_keys
            
            # get_by_id should return None
            config = SystemConfigRepository.get_by_id(config_id)
            assert config is None

    def test_scheduled_audit_report_soft_delete(self, app, admin_user_id):
        """Test soft delete for scheduled_audit_reports."""
        with app.app_context():
            # Create report
            with get_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO scheduled_audit_reports (name, description, format, frequency, parameters, next_run_time, created_by, updated_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, ("TEST_Report_1", "Test report", "CSV", "daily", '{}', "2024-01-01 00:00:00", admin_user_id, admin_user_id))
                report_id = cur.fetchone()["id"]
            
            # Soft delete
            ScheduledAuditReportRepository.delete(report_id)
            
            # Should not appear in list
            reports = ScheduledAuditReportRepository.list_all()
            report_names = [r["name"] for r in reports]
            assert "TEST_Report_1" not in report_names
            
            # get_by_id should return None
            report = ScheduledAuditReportRepository.get_by_id(report_id)
            assert report is None
            
            # But record should exist with deleted_at
            with get_cursor() as cur:
                cur.execute("SELECT deleted_at FROM scheduled_audit_reports WHERE id = %s", (report_id,))
                row = cur.fetchone()
                assert row is not None
                assert row["deleted_at"] is not None

    def test_soft_delete_uses_stored_procedure(self, app, admin_user_id):
        """Test that soft delete calls the stored procedure."""
        with app.app_context():
            # Create backup
            with get_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO system_backups (backup_name, backup_type, file_path, size, status, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, ("TEST_SP_Delete", "full", "/tmp/test.backup", 1024, "success", admin_user_id))
                backup_id = cur.fetchone()["id"]
            
            # Mock the stored procedure call
            with patch('app.repositories.system_backup_repo.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_get_cursor.return_value.__enter__.return_value = mock_cur
                
                SystemBackupRepository.delete_by_id(backup_id)
                
                # Verify sp_system_backup_delete was called
                mock_cur.execute.assert_called()
                call_args = mock_cur.execute.call_args[0]
                assert "sp_system_backup_delete" in call_args[0]
                assert backup_id in call_args[1]

    def test_list_all_excludes_deleted_by_default(self, app, admin_user_id):
        """Test that list_all excludes soft-deleted records by default."""
        with app.app_context():
            # Create two backups
            with get_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO system_backups (backup_name, backup_type, file_path, size, status, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, ("TEST_List_1", "full", "/tmp/test1.backup", 1024, "success", admin_user_id))
                id1 = cur.fetchone()["id"]
                cur.execute("""
                    INSERT INTO system_backups (backup_name, backup_type, file_path, size, status, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, ("TEST_List_2", "full", "/tmp/test2.backup", 2048, "success", admin_user_id))
                id2 = cur.fetchone()["id"]
            
            # Soft delete one
            SystemBackupRepository.delete_by_id(id1)
            
            # list_all should only show the non-deleted one
            backups = SystemBackupRepository.list_all()
            backup_names = [b["backup_name"] for b in backups]
            assert "TEST_List_1" not in backup_names
            assert "TEST_List_2" in backup_names
            
            # list_all with include_deleted=True should show both
            all_backups = SystemBackupRepository.list_all(include_deleted=True)
            all_names = [b["backup_name"] for b in all_backups]
            assert "TEST_List_1" in all_names
            assert "TEST_List_2" in all_names

    def test_list_all_can_include_deleted(self, app, admin_user_id):
        """Test that list_all with include_deleted=True shows deleted records."""
        with app.app_context():
            # Create and delete a backup
            with get_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO system_backups (backup_name, backup_type, file_path, size, status, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, ("TEST_Include_Deleted", "full", "/tmp/test.backup", 1024, "success", admin_user_id))
                backup_id = cur.fetchone()["id"]
            
            SystemBackupRepository.delete_by_id(backup_id)
            
            # Default list_all should not show it
            backups = SystemBackupRepository.list_all()
            backup_names = [b["backup_name"] for b in backups]
            assert "TEST_Include_Deleted" not in backup_names
            
            # With include_deleted=True, it should appear
            all_backups = SystemBackupRepository.list_all(include_deleted=True)
            all_names = [b["backup_name"] for b in all_backups]
            assert "TEST_Include_Deleted" in all_names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])