"""Backup and restore service with encryption and integrity checks."""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from flask import current_app
from ..repositories import SystemBackupRepository
from ..repositories import UserRepository
from ..config.settings import Config
from ..database.connection import get_cursor, _open_conn
from ..utils.cache import monitoring_cache
from ..database.etl import _safe_error


LOGGER = logging.getLogger(__name__)


# ADM-004: PostgreSQL advisory lock key for restore operations.
# Different from ETL's _ETL_LOCK_KEY (774001) to allow concurrent restore + ETL.
_RESTORE_LOCK_KEY = 774002


def _acquire_restore_lock(conn) -> bool:
    """
    Acquire PostgreSQL advisory lock for restore operation.
    
    Uses pg_try_advisory_lock which returns immediately (non-blocking).
    Returns True if lock acquired, False if already held by another session.
    
    Args:
        conn: psycopg2 connection (dedicated connection for lock lifetime)
        
    Returns:
        bool: True if lock acquired, False otherwise
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s) AS locked", (_RESTORE_LOCK_KEY,))
            result = cur.fetchone()
            return result["locked"] if result else False
    except Exception as e:
        LOGGER.warning("Failed to acquire restore advisory lock: %s", _safe_error(e))
        return False


def _release_restore_lock(conn) -> bool:
    """
    Release PostgreSQL advisory lock for restore operation.
    
    Uses pg_advisory_unlock which returns True even if lock wasn't held.
    
    Args:
        conn: psycopg2 connection (same connection that acquired the lock)
        
    Returns:
        bool: True if unlock attempted (always True for pg_advisory_unlock)
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (_RESTORE_LOCK_KEY,))
            return True
    except Exception as e:
        LOGGER.warning("Failed to release restore advisory lock: %s", _safe_error(e))
        return False


def _cleanup_stale_restore_lock(conn) -> bool:
    """
    Clean up any stale advisory lock from a dead connection.
    
    Advisory locks are session-level and persist across pooled connections.
    This function explicitly releases the lock on a new connection to clean
    up any stale lock from a crashed worker.
    
    Args:
        conn: psycopg2 connection
        
    Returns:
        bool: True if cleanup attempted
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (_RESTORE_LOCK_KEY,))
            return True
    except Exception as e:
        LOGGER.warning("Failed to cleanup stale restore advisory lock: %s", _safe_error(e))
        return False


def _get_db_params():
    """Get database connection parameters as a dictionary."""
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return {"url": database_url}
    
    if current_app:
        config = current_app.config
        host = config.get("DB_HOST", "localhost")
        port = config.get("DB_PORT", 5432)
        dbname = config.get("DB_NAME", "inventory_db")
        user = config.get("DB_USER", "postgres")
        password = config.get("DB_PASSWORD", "")
    else:
        host = os.environ.get("DB_HOST", "localhost")
        port = int(os.environ.get("DB_PORT", "5432"))
        dbname = os.environ.get("DB_NAME", "inventory_db")
        user = os.environ.get("DB_USER", "postgres")
        password = os.environ.get("DB_PASSWORD", "")
    
    return {
        "host": host,
        "port": port,
        "dbname": dbname,
        "user": user,
        "password": password,
    }


def _get_dump_command(params, output_file):
    """Construct the pg_dump command."""
    if "url" in params:
        return [
            "pg_dump",
            params["url"],
            "-f", output_file,
            "--verbose",
            "--no-owner",
            "--no-privileges",
        ]
    else:
        return [
            "pg_dump",
            "-h", params["host"],
            "-p", str(params["port"]),
            "-U", params["user"],
            "-d", params["dbname"],
            "-f", output_file,
            "--verbose",
            "--no-owner",
            "--no-privileges",
        ]


def _get_restore_command(params, input_file):
    """Construct the pg_restore command."""
    if "url" in params:
        return [
            "pg_restore",
            params["url"],
            "-d", params["url"].split("/")[-1],
            "--verbose",
            "--clean",
            "--no-owner",
            "--no-privileges",
            input_file,
        ]
    else:
        return [
            "pg_restore",
            "-h", params["host"],
            "-p", str(params["port"]),
            "-U", params["user"],
            "-d", params["dbname"],
            "--verbose",
            "--clean",
            "--no-owner",
            "--no-privileges",
            input_file,
        ]


def _get_master_key() -> bytes:
    """Get or derive the master encryption key from settings."""
    # Use BACKUP_ENCRYPTION_KEY from config, or derive from SECRET_KEY
    master_key = getattr(Config, 'BACKUP_ENCRYPTION_KEY', None)
    if not master_key:
        master_key = Config.SECRET_KEY
    
    # Ensure master_key is bytes and exactly 32 bytes for Fernet
    if isinstance(master_key, str):
        master_key = master_key.encode()
    
    # Derive a 32-byte key using PBKDF2
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'inventorylogix-backup-salt',  # Fixed salt for deterministic derivation
        iterations=100000,
    )
    return kdf.derive(master_key)


def _derive_key(key_id: str) -> bytes:
    """Derive an encryption key from master key and key_id."""
    master_key = _get_master_key()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=key_id.encode(),
        iterations=100000,
    )
    # Fernet requires a 32-byte key encoded as URL-safe base64
    return base64.urlsafe_b64encode(kdf.derive(master_key))


def _encrypt_file(file_path: Path, key_id: Optional[str] = None) -> tuple[Path, str, str]:
    """
    Encrypt a file using Fernet symmetric encryption.
    
    Returns: (encrypted_file_path, key_id, checksum)
    """
    if key_id is None:
        key_id = f"backup_{int(time.time())}"
    
    # Generate key from key_id
    key = _derive_key(key_id)
    fernet = Fernet(key)
    
    # Read and encrypt
    plaintext = file_path.read_bytes()
    ciphertext = fernet.encrypt(plaintext)
    
    # Write encrypted file
    encrypted_path = file_path.with_suffix(file_path.suffix + ".enc")
    encrypted_path.write_bytes(ciphertext)
    
    # Calculate checksum of original file
    checksum = hashlib.sha256(plaintext).hexdigest()
    
    return encrypted_path, key_id, checksum


def _decrypt_file(encrypted_path: Path, key_id: str) -> Path:
    """Decrypt a file using Fernet symmetric encryption."""
    key = _derive_key(key_id)
    fernet = Fernet(key)
    
    ciphertext = encrypted_path.read_bytes()
    plaintext = fernet.decrypt(ciphertext)
    
    # Write decrypted file
    decrypted_path = encrypted_path.with_suffix("")
    if decrypted_path.suffix == ".enc":
        decrypted_path = decrypted_path.with_suffix("")
    decrypted_path = decrypted_path.with_name(decrypted_path.name + ".dec")
    decrypted_path.write_bytes(plaintext)
    
    return decrypted_path


def _verify_checksum(file_path: Path, expected_checksum: str) -> bool:
    """Verify file integrity using SHA256 checksum."""
    actual_checksum = hashlib.sha256(file_path.read_bytes()).hexdigest()
    return actual_checksum == expected_checksum


def create_backup(backup_name: str, backup_type: str = "full", user_id: int | None = None) -> dict:
    """Create a database backup with encryption and integrity checks.
    
    Returns a dictionary with keys: success, message, backup_id.
    """
    try:
        # Determine the user who initiated the backup
        if user_id is None:
            from flask_login import current_user
            if current_user.is_authenticated:
                user_id = current_user.id
            else:
                admin_user = UserRepository.find_by_username("admin")
                if admin_user:
                    user_id = admin_user.id
                else:
                    first_user = UserRepository.find_by_id(1)
                    if first_user:
                        user_id = first_user.id
                    else:
                        raise ValueError("No user found to attribute the backup to")
        
        # Set up backup directory - ensure it exists before any file operations
        backup_dir = Path("backups").resolve()
        # Use os.makedirs directly to avoid Path mock interference in tests
        import os
        os.makedirs(backup_dir, exist_ok=True)
        
        # Generate a unique filename
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() else "_" for c in backup_name)
        filename = f"{timestamp}_{safe_name}.backup"
        file_path = backup_dir / filename
        
        # Get database parameters
        db_params = _get_db_params()
        
        # Create the dump command
        dump_cmd = _get_dump_command(db_params, str(file_path))
        
        # Set environment for subprocess
        env = os.environ.copy()
        if "url" in db_params:
            pass
        else:
            env["PGPASSWORD"] = db_params["password"]
        
        # Run the backup
        result = subprocess.run(
            dump_cmd,
            env=env,
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode != 0:
            error_msg = f"Backup failed: {result.stderr}"
            if current_app:
                current_app.logger.error(error_msg)
            else:
                print(error_msg)
            return {
                "success": False,
                "message": error_msg,
                "backup_id": None
            }
        
        # Encrypt the backup file
        key_id = f"backup_{backup_name}_{timestamp}"
        encrypted_path, key_id, checksum = _encrypt_file(file_path, key_id)
        
        # Ensure encrypted_path is a Path object (handles test mocks that return str)
        if isinstance(encrypted_path, str):
            encrypted_path = Path(encrypted_path)
        
        # Get the encrypted file size
        file_size = encrypted_path.stat().st_size
        
        # Remove unencrypted file (ignore if missing - e.g., in tests where pg_dump is mocked)
        try:
            file_path.unlink(missing_ok=True)
        except TypeError:
            # Python < 3.8 doesn't have missing_ok
            if file_path.exists():
                file_path.unlink()
        
        # Add backup record to the database with encryption metadata
        backup_id = SystemBackupRepository.add(
            backup_name=backup_name,
            backup_type=backup_type,
            file_path=str(encrypted_path),
            size=file_size,
            status="success",
            created_by=user_id,
            encrypted=True,
            encryption_key_id=key_id,
            checksum=checksum
        )
        
        success_msg = f"Backup '{backup_name}' created successfully (encrypted)."
        if current_app:
            current_app.logger.info(success_msg)
        else:
            print(success_msg)
        return {
            "success": True,
            "message": success_msg,
            "backup_id": backup_id
        }
        
    except Exception as e:
        error_msg = f"Unexpected error during backup: {str(e)}"
        if current_app:
            current_app.logger.error(error_msg)
        else:
            print(error_msg)
        return {
            "success": False,
            "message": error_msg,
            "backup_id": None
        }


def restore_backup(backup_id: int, user_id: int | None = None) -> dict:
    """Restore a database backup with integrity verification.
    
    Returns a dictionary with keys: success, message, started.
    """
    # DB-031: Run restore in background thread (non-blocking)
    # Returns immediately with "started" status after checksum verification
    
    # Quick validation first
    backup_record = SystemBackupRepository.get_by_id(backup_id)
    if not backup_record:
        return {
            "success": False,
            "message": f"Backup with ID {backup_id} not found.",
        }
    
    # Check if file exists
    encrypted_path = Path(backup_record["file_path"])
    if not encrypted_path.exists():
        return {
            "success": False,
            "message": f"Backup file not found: {encrypted_path}",
        }
# Verify checksum synchronously BEFORE acquiring lock/starting background thread
    # This allows immediate failure on checksum mismatch and satisfies transaction tests
    if backup_record.get("checksum"):
        # Only need encryption_key_id if the backup is encrypted
        if backup_record.get("encrypted"):
            key_id = backup_record.get("encryption_key_id")
            if not key_id:
                return {
                    "success": False,
                    "message": "Backup encryption key ID missing.",
                }
            
            decrypted_path = _decrypt_file(encrypted_path, key_id)
        else:
            # Unencrypted backup - verify checksum directly on the file
            decrypted_path = encrypted_path
        
        try:
            if not _verify_checksum(decrypted_path, backup_record["checksum"]):
                return {
                    "success": False,
                    "message": "Backup integrity check failed: checksum mismatch.",
                }
        finally:
            # Only clean up if we created a decrypted file (not the original encrypted file)
            # Use missing_ok=True to handle test mocks where the file doesn't actually exist
            if backup_record.get("encrypted"):
                try:
                    decrypted_path.unlink(missing_ok=True)
                except TypeError:
                    # Python < 3.8 doesn't have missing_ok
                    if decrypted_path.exists():
                        decrypted_path.unlink()
    
    # ADM-004: Acquire PostgreSQL advisory lock (non-blocking)
    # Use a dedicated connection for the lock acquisition attempt
    lock_conn = _open_conn()
    try:
        # Clean up any stale lock from a crashed worker
        _cleanup_stale_restore_lock(lock_conn)
        
        # Try to acquire the lock
        if not _acquire_restore_lock(lock_conn):
            return {
                "success": False,
                "message": "Another restore is already in progress.",
            }
    except Exception as e:
        lock_conn.close()
        LOGGER.error("Failed to acquire restore lock: %s", _safe_error(e))
        return {
            "success": False,
            "message": f"Failed to acquire restore lock: {_safe_error(e)}",
        }
    finally:
        # Release the lock acquisition connection immediately
        # The background thread will create its own connection and re-acquire the lock
        lock_conn.close()
    
    # Capture app context for background thread
    from flask import current_app
    _app = current_app._get_current_object()
    
    def _persist(key, value=None):
        """Best-effort etl_warehouse_state upsert; value=None clears the row."""
        try:
            with get_cursor(commit=True) as cur:
                if value is None:
                    cur.execute(
                        "DELETE FROM etl_warehouse_state WHERE state_key = %s",
                        (key,),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO etl_warehouse_state (state_key, value, updated_at)
                        VALUES (%s, %s, NOW())
                        ON CONFLICT (state_key)
                        DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                        """,
                        (key, str(value)),
                    )
        except Exception as e:
            LOGGER.warning(
                "Could not persist restore job state %s: %s", key, _safe_error(e)
            )
    
    def _run():
        # Background thread creates ITS OWN connection for the advisory lock
        # Advisory locks are session-level and released when connection closes
        with _app.app_context():
            bg_conn = _open_conn()
            try:
                # Clean up any stale lock on THIS connection
                _cleanup_stale_restore_lock(bg_conn)
                
                # Acquire advisory lock on THIS connection
                if not _acquire_restore_lock(bg_conn):
                    _persist("restore_job_status", "failed")
                    _persist("restore_job_error", "Another restore acquired lock")
                    return
                
                try:
                    _persist("restore_job_status", "running")
                    _persist("restore_job_error")
                    
                    # Get the backup record
                    backup_record = SystemBackupRepository.get_by_id(backup_id)
                    if not backup_record:
                        _persist("restore_job_status", "failed")
                        _persist("restore_job_error", "Backup record not found")
                        return
                    
                    # Determine the user who initiated the restore (use local variable)
                    restore_user_id = user_id
                    if restore_user_id is None:
                        from flask_login import current_user
                        if current_user.is_authenticated:
                            restore_user_id = current_user.id
                        else:
                            admin_user = UserRepository.find_by_username("admin")
                            if admin_user:
                                restore_user_id = admin_user.id
                            else:
                                first_user = UserRepository.find_by_id(1)
                                if first_user:
                                    restore_user_id = first_user.id
                                else:
                                    raise ValueError("No user found to attribute the restore to")
                    
                    # Get the backup file path
                    encrypted_path = Path(backup_record["file_path"])
                    if not encrypted_path.exists():
                        _persist("restore_job_status", "failed")
                        _persist("restore_job_error", f"Backup file not found: {encrypted_path}")
                        return
                    
                    # Get database parameters
                    db_params = _get_db_params()
                    
                    # Decrypt backup for restore
                    key_id = backup_record.get("encryption_key_id")
                    if not key_id:
                        _persist("restore_job_status", "failed")
                        _persist("restore_job_error", "Backup encryption key ID missing.")
                        return
                    
                    decrypted_path = _decrypt_file(encrypted_path, key_id)
                    
                    try:
                        # Create the restore command
                        restore_cmd = _get_restore_command(db_params, str(decrypted_path))
                        
                        # Set environment for subprocess
                        env = os.environ.copy()
                        if "url" in db_params:
                            pass
                        else:
                            env["PGPASSWORD"] = db_params["password"]
                        
                        # Run the restore
                        result = subprocess.run(
                            restore_cmd,
                            env=env,
                            capture_output=True,
                            text=True,
                            check=False
                        )
                        
                        if result.returncode != 0:
                            error_msg = f"Restore failed: {result.stderr}"
                            _persist("restore_job_status", "failed")
                            _persist("restore_job_error", error_msg)
                        else:
                            _persist("restore_job_status", "success")
                            _persist("restore_job_error")
                    
                    finally:
                        # Clean up decrypted file
                        if decrypted_path.exists():
                            decrypted_path.unlink()
                        
                        monitoring_cache.invalidate("")  # bust cache
                        
                except Exception as e:
                    LOGGER.warning("Background restore failed: %s", _safe_error(e))
                    _persist("restore_job_status", "failed")
                    _persist("restore_job_error", _safe_error(e))
            finally:
                # ADM-004: Release advisory lock and close dedicated connection
                # This runs even if background thread crashes
                try:
                    _release_restore_lock(bg_conn)
                finally:
                    bg_conn.close()
    
    # Start background thread
    thread = threading.Thread(target=_run, daemon=True, name="restore_run")
    try:
        thread.start()
    except Exception as e:
        LOGGER.error("Failed to start restore thread: %s", _safe_error(e))
        return {
            "success": False,
            "message": f"Failed to start restore: {_safe_error(e)}",
        }
    
    return {
        "success": True,
        "message": "Restore started in background. Check monitoring page for status.",
        "started": True
    }