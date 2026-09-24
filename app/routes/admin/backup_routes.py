"""Admin backup and restore routes."""
from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.security import write_roles_required, roles_required
from app.services import backup_service
from app.repositories import SystemBackupRepository

admin_backup_bp = Blueprint("admin_backup", __name__, url_prefix="/admin/backup")


@admin_backup_bp.route("/")
@login_required
@roles_required("admin")
def index():
    """List all backups."""
    backups = SystemBackupRepository.list_all()
    return render_template("admin/backup/index.html", backups=backups, active_page="backup")


@admin_backup_bp.route("/create", methods=["GET", "POST"])
@login_required
@roles_required("admin")
def create():
    """Create a new backup."""
    if request.method == "GET":
        return render_template("admin/backup/create.html", active_page="backup")
    
    # POST request
    backup_name = request.form.get("backup_name", "").strip()
    backup_type = request.form.get("backup_type", "full")
    
    if not backup_name:
        flash("Backup name is required.", "error")
        return redirect(url_for("admin_backup.create"))
    
    result = backup_service.create_backup(
        backup_name=backup_name,
        backup_type=backup_type,
        user_id=current_user.id
    )
    
    if result["success"]:
        flash(result["message"], "success")
        return redirect(url_for("admin_backup.index"))
    else:
        flash(result["message"], "error")
        return redirect(url_for("admin_backup.create"))


@admin_backup_bp.route("/restore/<int:backup_id>", methods=["POST"])
@login_required
@roles_required("admin")
def restore(backup_id: int):
    """Restore a backup."""
    result = backup_service.restore_backup(
        backup_id=backup_id,
        user_id=current_user.id
    )
    
    if result["success"]:
        flash(result["message"], "success")
    else:
        flash(result["message"], "error")
    
    return redirect(url_for("admin_backup.index"))


@admin_backup_bp.route("/delete/<int:backup_id>", methods=["POST"])
@login_required
@roles_required("admin")
def delete(backup_id: int):
    """Delete a backup record."""
    # First, get the backup record to delete the file if needed
    backup_record = SystemBackupRepository.get_by_id(backup_id)
    if backup_record:
        # Delete the file if it exists
        import os
        from pathlib import Path
        file_path = Path(backup_record["file_path"])
        if file_path.exists():
            try:
                file_path.unlink()
                current_app.logger.info(f"Deleted backup file: {file_path}")
            except Exception as e:
                current_app.logger.error(f"Error deleting backup file {file_path}: {e}")
        
        # Delete the record from the database
        SystemBackupRepository.delete_by_id(backup_id)
        flash(f"Backup '{backup_record['backup_name']}' deleted successfully.", "success")
    else:
        flash("Backup not found.", "error")
    
    return redirect(url_for("admin_backup.index"))