"""Backup and restore service."""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from flask import current_app
from ..repositories import SystemBackupRepository
from ..repositories import UserRepository
from ..models import UserProxy


def _get_db_params():
    """Get database connection parameters as a dictionary.
    Prioritizes DATABASE_URL, otherwise uses individual components.
    """
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return {"url": database_url}
    
    # Fallback to individual components (from app config)
    # We'll try to get from current_app.config if available, otherwise from environment
    if current_app:
        config = current_app.config
        host = config.get("DB_HOST", "localhost")
        port = config.get("DB_PORT", 5432)
        dbname = config.get("DB_NAME", "inventory_db")
        user = config.get("DB_USER", "postgres")
        password = config.get("DB_PASSWORD", "")
    else:
        # Fallback to environment variables
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
        # Using connection URL
        return [
            "pg_dump",
            params["url"],
            "-f", output_file,
            "--verbose",
            "--no-owner",
            "--no-privileges",
        ]
    else:
        # Using individual parameters
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
        # Using connection URL
        return [
            "pg_restore",
            params["url"],
            "-d", params["url"].split("/")[-1],  # Extract database name from URL
            "--verbose",
            "--clean",
            "--no-owner",
            "--no-privileges",
            input_file,
        ]
    else:
        # Using individual parameters
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


def create_backup(backup_name: str, backup_type: str = "full", user_id: int | None = None) -> dict:
    """Create a database backup and store metadata.
    
    Returns a dictionary with keys: success, message, backup_id.
    """
    try:
        # Determine the user who initiated the backup
        if user_id is None:
            # Try to get the current user from Flask context
            from flask_login import current_user
            if current_user.is_authenticated:
                user_id = current_user.id
            else:
                # Fallback to a system user or raise an error
                # For now, we'll use the first admin user we find
                admin_user = UserRepository.find_by_username("admin")
                if admin_user:
                    user_id = admin_user.id
                else:
                    # If no admin user, use the first user
                    first_user = UserRepository.find_by_id(1)
                    if first_user:
                        user_id = first_user.id
                    else:
                        raise ValueError("No user found to attribute the backup to")
        
        # Set up backup directory
        backup_dir = Path("backups")
        backup_dir.mkdir(exist_ok=True)
        
        # Generate a unique filename
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() else "_" for c in backup_name)
        filename = f"{timestamp}_{safe_name}.backup"
        file_path = backup_dir / filename
        
        # Get database parameters
        db_params = _get_db_params()
        
        # Create the dump command
        dump_cmd = _get_dump_command(db_params, str(file_path))
        
        # Set environment for subprocess (to avoid password prompt)
        env = os.environ.copy()
        if "url" in db_params:
            # Extract password from URL if needed, but pg_dump can handle it in the URL
            pass
        else:
            env["PGPASSWORD"] = db_params["password"]
        
        # Run the backup
        result = subprocess.run(
            dump_cmd,
            env=env,
            capture_output=True,
            text=True,
            check=False  # We'll handle the return code ourselves
        )
        
        if result.returncode != 0:
            error_msg = f"Backup failed: {result.stderr}"
            current_app.logger.error(error_msg) if current_app else print(error_msg)
            return {
                "success": False,
                "message": error_msg,
                "backup_id": None
            }
        
        # Get the file size
        file_size = file_path.stat().st_size
        
        # Add backup record to the database
        backup_id = SystemBackupRepository.add(
            backup_name=backup_name,
            backup_type=backup_type,
            file_path=str(file_path),
            size=file_size,
            status="success",
            created_by=user_id
        )
        
        success_msg = f"Backup '{backup_name}' created successfully."
        current_app.logger.info(success_msg) if current_app else print(success_msg)
        return {
            "success": True,
            "message": success_msg,
            "backup_id": backup_id
        }
        
    except Exception as e:
        error_msg = f"Unexpected error during backup: {str(e)}"
        current_app.logger.error(error_msg) if current_app else print(error_msg)
        return {
            "success": False,
            "message": error_msg,
            "backup_id": None
        }


def restore_backup(backup_id: int, user_id: int | None = None) -> dict:
    """Restore a database backup from a backup record.
    
    Returns a dictionary with keys: success, message.
    """
    try:
        # Get the backup record
        backup_record = SystemBackupRepository.get_by_id(backup_id)
        if not backup_record:
            return {
                "success": False,
                "message": f"Backup with ID {backup_id} not found.",
            }
        
        # Determine the user who initiated the restore
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
                        raise ValueError("No user found to attribute the restore to")
        
        # Get the backup file path
        file_path = Path(backup_record["file_path"])
        if not file_path.exists():
            return {
                "success": False,
                "message": f"Backup file not found: {file_path}",
            }
        
        # Get database parameters
        db_params = _get_db_params()
        
        # Create the restore command
        restore_cmd = _get_restore_command(db_params, str(file_path))
        
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
            current_app.logger.error(error_msg) if current_app else print(error_msg)
            return {
                "success": False,
                "message": error_msg,
            }
        
        # Update the backup record status? Or we could leave it as is.
        # For now, we'll just return success.
        success_msg = f"Backup '{backup_record['backup_name']}' restored successfully."
        current_app.logger.info(success_msg) if current_app else print(success_msg)
        return {
            "success": True,
            "message": success_msg,
        }
        
    except Exception as e:
        error_msg = f"Unexpected error during restore: {str(e)}"
        current_app.logger.error(error_msg) if current_app else print(error_msg)
        return {
            "success": False,
            "message": error_msg,
        }