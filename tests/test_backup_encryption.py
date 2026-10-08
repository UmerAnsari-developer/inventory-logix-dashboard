"""Tests for backup encryption and integrity."""
from __future__ import annotations

import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.services import backup_service
from app.config.settings import Config


class TestBackupEncryption:
    """Test backup encryption with cryptography.fernet."""

    def test_cryptography_in_requirements(self):
        """Test that cryptography is in requirements.txt."""
        req_path = Path("requirements.txt")
        content = req_path.read_text()
        assert "cryptography>=" in content

    def test_backup_encryption_key_in_settings(self):
        """Test that BACKUP_ENCRYPTION_KEY is in settings."""
        # This will be added in GREEN phase
        assert hasattr(Config, 'BACKUP_ENCRYPTION_KEY')

    def test_encrypt_file_returns_encrypted_path_key_checksum(self, app):
        """Test _encrypt_file returns encrypted path, key ID, and checksum."""
        with app.app_context():
            # Create a test file in temp directory
            with tempfile.NamedTemporaryFile(delete=False, suffix=".backup") as tmp:
                test_file = Path(tmp.name)
                test_file.write_bytes(b"test backup content")
            
            try:
                encrypted_path, key_id, checksum = backup_service._encrypt_file(test_file)
                
                assert encrypted_path is not None
                assert encrypted_path != str(test_file)
                assert key_id is not None
                assert checksum is not None
                assert len(checksum) == 64  # SHA256 hex
                
                # Encrypted file should exist
                assert Path(encrypted_path).exists()
                
                # Original file should still exist (we don't delete it)
                assert test_file.exists()
            finally:
                # Cleanup
                if test_file.exists():
                    test_file.unlink()
                encrypted_path = Path(encrypted_path) if 'encrypted_path' in locals() else None
                if encrypted_path and encrypted_path.exists():
                    encrypted_path.unlink()

    def test_decrypt_file_restores_original(self, app):
        """Test _decrypt_file restores original content."""
        with app.app_context():
            # Create a test file in temp directory
            with tempfile.NamedTemporaryFile(delete=False, suffix=".backup") as tmp:
                test_file = Path(tmp.name)
                original_content = b"test backup content for decryption"
                test_file.write_bytes(original_content)
            
            try:
                # Encrypt
                encrypted_path, key_id, checksum = backup_service._encrypt_file(test_file)
                
                # Decrypt
                decrypted_path = backup_service._decrypt_file(Path(encrypted_path), key_id)
                
                assert decrypted_path is not None
                assert Path(decrypted_path).exists()
                
                # Content should match
                decrypted_content = Path(decrypted_path).read_bytes()
                assert decrypted_content == original_content
            finally:
                # Cleanup
                for p in [test_file, Path(str(encrypted_path) + ".enc"), Path(str(encrypted_path) + ".dec")]:
                    if p.exists():
                        p.unlink()

    def test_verify_checksum_validates_integrity(self, app):
        """Test _verify_checksum validates file integrity."""
        with app.app_context():
            with tempfile.NamedTemporaryFile(delete=False, suffix=".backup") as tmp:
                test_file = Path(tmp.name)
                test_file.write_bytes(b"content for checksum")
            
            try:
                # Get checksum
                import hashlib
                expected_checksum = hashlib.sha256(test_file.read_bytes()).hexdigest()
                
                # Verify correct checksum
                assert backup_service._verify_checksum(test_file, expected_checksum) is True
                
                # Verify incorrect checksum fails
                assert backup_service._verify_checksum(test_file, "wrong_checksum") is False
            finally:
                if test_file.exists():
                    test_file.unlink()

    def test_encryption_uses_fernet(self, app):
        """Test that encryption uses Fernet symmetric encryption."""
        with app.app_context():
            with tempfile.NamedTemporaryFile(delete=False, suffix=".backup") as tmp:
                test_file = Path(tmp.name)
                test_file.write_bytes(b"fernet test content")
            
            try:
                encrypted_path, key_id, checksum = backup_service._encrypt_file(test_file)
                
                # Verify it's actually encrypted (not plaintext)
                encrypted_content = Path(encrypted_path).read_bytes()
                assert b"fernet test content" not in encrypted_content
                assert len(encrypted_content) > len(b"fernet test content")
            finally:
                for p in [test_file, Path(encrypted_path)]:
                    if p.exists():
                        p.unlink()

    def test_key_derivation_from_master_key(self, app):
        """Test that encryption keys are derived from master key."""
        with app.app_context():
            # The same master key should produce the same derived key for same key_id
            with tempfile.NamedTemporaryFile(delete=False, suffix=".backup") as tmp:
                test_file = Path(tmp.name)
                test_file.write_bytes(b"key derivation test")
            
            try:
                encrypted_path1, key_id1, checksum1 = backup_service._encrypt_file(test_file, key_id="backup_1")
                encrypted_path2, key_id2, checksum2 = backup_service._encrypt_file(test_file, key_id="backup_1")
                
                # Same key_id should produce same key_id (deterministic)
                assert key_id1 == key_id2
                
                # Both should decrypt to same content
                decrypted1 = backup_service._decrypt_file(Path(encrypted_path1), key_id1)
                decrypted2 = backup_service._decrypt_file(Path(encrypted_path2), key_id2)
                
                assert Path(decrypted1).read_bytes() == b"key derivation test"
                assert Path(decrypted2).read_bytes() == b"key derivation test"
            finally:
                for p in [test_file, Path(encrypted_path1), Path(encrypted_path2),
                          Path(decrypted1), Path(decrypted2)]:
                    if p.exists():
                        p.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])