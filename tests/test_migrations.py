"""Tests for soft delete migration on admin tables."""
from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from app.database import get_cursor
from app.repositories import UserRepository


@pytest.fixture
def admin_user_id(app):
    """Get the admin user ID dynamically (avoids hardcoded ID=1)."""
    with app.app_context():
        admin = UserRepository.find_by_username("admin")
        assert admin is not None, "admin user must exist"
        return admin.id


class TestSoftDeleteMigration:
    """Test soft delete columns added to admin tables via alembic migration."""

    @pytest.fixture(autouse=True)
    def setup_db(self, app):
        """Set up test database."""
        with app.app_context():
            yield

    def test_migration_file_exists(self):
        """Test that migration file for soft delete exists."""
        import glob
        migration_files = glob.glob("migrations/versions/*soft_delete*")
        assert len(migration_files) > 0, "Soft delete migration file not found"

    def test_system_backups_has_deleted_at(self, app):
        """Test that system_backups table has deleted_at column."""
        with app.app_context():
            with get_cursor() as cur:
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'system_backups' AND column_name = 'deleted_at'
                """)
                row = cur.fetchone()
                assert row is not None, "system_backups.deleted_at column missing"

    def test_system_config_overrides_has_deleted_at(self, app):
        """Test that system_config_overrides table has deleted_at column."""
        with app.app_context():
            with get_cursor() as cur:
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'system_config_overrides' AND column_name = 'deleted_at'
                """)
                row = cur.fetchone()
                assert row is not None, "system_config_overrides.deleted_at column missing"

    def test_scheduled_audit_reports_has_deleted_at(self, app):
        """Test that scheduled_audit_reports table has deleted_at column."""
        with app.app_context():
            with get_cursor() as cur:
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'scheduled_audit_reports' AND column_name = 'deleted_at'
                """)
                row = cur.fetchone()
                assert row is not None, "scheduled_audit_reports.deleted_at column missing"

    def test_soft_delete_index_exists(self, app):
        """Test that partial index for soft delete exists."""
        with app.app_context():
            with get_cursor() as cur:
                # Check system_backups
                cur.execute("""
                    SELECT indexname FROM pg_indexes
                    WHERE tablename = 'system_backups' AND indexname LIKE '%deleted_at%'
                """)
                indexes = cur.fetchall()
                assert len(indexes) > 0, "Partial index for system_backups.deleted_at missing"

    def test_repositories_filter_deleted(self, app, admin_user_id):
        """Test that repositories filter out soft-deleted records."""
        with app.app_context():
            from app.repositories import SystemBackupRepository, SystemConfigRepository, ScheduledAuditReportRepository
            
            with get_cursor(commit=True) as cur:
                # Insert a soft-deleted record
                cur.execute("""
                    INSERT INTO system_backups (backup_name, backup_type, file_path, size, status, created_by, deleted_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    RETURNING id
                """, ("TEST_DELETED", "full", "/tmp/test.backup", 100, "success", admin_user_id))
                deleted_id = cur.fetchone()["id"]
                
                # Insert active record
                cur.execute("""
                    INSERT INTO system_backups (backup_name, backup_type, file_path, size, status, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, ("TEST_ACTIVE", "full", "/tmp/test2.backup", 200, "success", admin_user_id))
                active_id = cur.fetchone()["id"]
            
            # list_all should only return active
            backups = SystemBackupRepository.list_all()
            backup_names = [b["backup_name"] for b in backups]
            assert "TEST_ACTIVE" in backup_names
            assert "TEST_DELETED" not in backup_names
            
            # get_by_id should return None for deleted
            deleted_backup = SystemBackupRepository.get_by_id(deleted_id)
            assert deleted_backup is None