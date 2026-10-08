"""Tests for backup restore transaction safety."""
from __future__ import annotations

import pytest
import os
import time
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock, call

from app.services import backup_service
from app.repositories import SystemBackupRepository
from app.database import get_cursor
from app.database.connection import _open_conn
from app.repositories import UserRepository


@pytest.fixture
def admin_user_id(app):
    """Get the admin user ID dynamically (avoids hardcoded ID=1)."""
    with app.app_context():
        admin = UserRepository.find_by_username("admin")
        assert admin is not None, "admin user must exist"
        return admin.id


# Wait for any in-flight restore daemon threads from prior tests
# Background threads hold the session-scoped advisory lock for ~1.5s;
# without this wait the lock races rotate between tests (flaky failures).
@pytest.fixture(autouse=True)
def _wait_for_restore_threads():
    deadline = time.time() + 5
    while time.time() < deadline:
        alive = [th for th in threading.enumerate() if th.name.endswith("_run") and th.is_alive()]
        if not alive:
            break
        time.sleep(0.2)
    
    # Clean up any stale advisory lock from dead connections
    try:
        conn = _open_conn()
        try:
            from app.services.backup_service import _cleanup_stale_restore_lock
            _cleanup_stale_restore_lock(conn)
        finally:
            conn.close()
    except Exception:
        pass  # Best effort cleanup


class TestBackupRestoreTransaction:
    """Test backup and restore with transaction safety."""

    @pytest.fixture(autouse=True)
    def setup_db(self, app):
        """Set up test database."""
        with app.app_context():
            # Ensure system_backups table has encryption columns
            with get_cursor(commit=True) as cur:
                cur.execute("""
                    ALTER TABLE system_backups 
                    ADD COLUMN IF NOT EXISTS encrypted BOOLEAN NOT NULL DEFAULT FALSE,
                    ADD COLUMN IF NOT EXISTS encryption_key_id VARCHAR(100),
                    ADD COLUMN IF NOT EXISTS checksum VARCHAR(64)
                """)
            yield
            # Cleanup
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM system_backups")

    def test_backup_creates_encrypted_file(self, app, admin_user_id):
        """Test that backup creates encrypted file with checksum."""
        with app.app_context():
            with patch('app.services.backup_service.subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="")
                
                # Mock file creation and encryption
                with patch('pathlib.Path.stat') as mock_stat:
                    mock_stat.return_value.st_size = 1024
                    
                    with patch('pathlib.Path.exists', return_value=True):
                        with patch('app.services.backup_service._encrypt_file') as mock_encrypt:
                            mock_encrypt.return_value = (Path("/tmp/test.backup.enc"), "key_123", "checksum_abc")
                            
                            result = backup_service.create_backup(
                                backup_name="test_backup",
                                backup_type="full",
                                user_id=admin_user_id
                            )
                
                assert result["success"] is True
                assert result["backup_id"] is not None
                
                # Verify backup record has encryption fields
                backup = SystemBackupRepository.get_by_id(result["backup_id"])
                assert backup is not None
                # Note: encryption will be implemented in GREEN phase

    def test_restore_validates_checksum_before_restore(self, app, admin_user_id):
        """Test that restore validates checksum before restoring."""
        with app.app_context():
            # Create a backup record with checksum
            with get_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO system_backups (backup_name, backup_type, file_path, size, status, created_by, checksum)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, ("test_restore", "full", "/tmp/test.backup", 1024, "success", admin_user_id, "abc123"))
                backup_id = cur.fetchone()["id"]
            
            with patch('app.services.backup_service.subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="")
                
                with patch('pathlib.Path.exists', return_value=True):
                    with patch('app.services.backup_service._verify_checksum', return_value=True) as mock_verify:
                        result = backup_service.restore_backup(backup_id=backup_id, user_id=admin_user_id)
                        
                        # Verify checksum was checked
                        mock_verify.assert_called_once()
                        assert result["success"] is True

    def test_restore_fails_on_checksum_mismatch(self, app, admin_user_id):
        """Test that restore fails when checksum doesn't match."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO system_backups (backup_name, backup_type, file_path, size, status, created_by, checksum)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, ("test_restore_fail", "full", "/tmp/test.backup", 1024, "success", admin_user_id, "abc123"))
                backup_id = cur.fetchone()["id"]
            
            with patch('app.services.backup_service.subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="")
                
                with patch('pathlib.Path.exists', return_value=True):
                    with patch('app.services.backup_service._verify_checksum', return_value=False):
                        result = backup_service.restore_backup(backup_id=backup_id, user_id=admin_user_id)
                        
                        assert result["success"] is False
                        assert "checksum" in result["message"].lower()
                        # Restore should not have been attempted
                        mock_run.assert_not_called()

    def test_restore_uses_transaction(self, app, admin_user_id):
        """Test that restore operates within a transaction (async behavior)."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO system_backups (backup_name, backup_type, file_path, size, status, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, ("test_tx", "full", "/tmp/test.backup", 1024, "success", admin_user_id))
                backup_id = cur.fetchone()["id"]
            
            with patch('app.services.backup_service.subprocess.run') as mock_run:
                # Simulate restore failure in background thread
                mock_run.return_value = MagicMock(returncode=1, stderr="pg_restore: error")
                
                with patch('pathlib.Path.exists', return_value=True):
                    result = backup_service.restore_backup(backup_id=backup_id, user_id=admin_user_id)
                    
                    # Async restore: returns started=True immediately
                    assert result["success"] is True
                    assert result.get("started") is True
                    
                    # Wait for background thread to complete
                    import time
                    time.sleep(1.5)
                    
                    # Verify background job recorded failure
                    with get_cursor() as cur:
                        cur.execute("SELECT value FROM etl_warehouse_state WHERE state_key = 'restore_job_status'")
                        row = cur.fetchone()
                        assert row is not None
                        assert row["value"] == "failed"

    def test_backup_stores_encryption_metadata(self, app, admin_user_id):
        """Test that backup stores encryption key ID and checksum."""
        with app.app_context():
            with patch('app.services.backup_service.subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="")
                
                with patch('pathlib.Path.stat') as mock_stat:
                    mock_stat.return_value.st_size = 1024
                    
                    with patch('pathlib.Path.exists', return_value=True):
                        with patch('app.services.backup_service._encrypt_file') as mock_encrypt:
                            mock_encrypt.return_value = (Path("/tmp/test.backup.enc"), "key_123", "checksum_abc")
                            
                            result = backup_service.create_backup(
                                backup_name="test_encrypted",
                                backup_type="full",
                                user_id=admin_user_id
                            )
                
                assert result["success"] is True
                
                backup = SystemBackupRepository.get_by_id(result["backup_id"])
                assert backup["encrypted"] is True
                assert backup["encryption_key_id"] == "key_123"
                assert backup["checksum"] == "checksum_abc"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])