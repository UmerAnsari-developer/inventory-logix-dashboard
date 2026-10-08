"""Admin system configuration override routes."""
from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import limiter
from app.security import write_roles_required, roles_required
from app.services import SystemConfigService
from app.repositories import system_config_repo

admin_system_config_bp = Blueprint("admin_system_config", __name__, url_prefix="/admin/system_config")


@admin_system_config_bp.route("/")
@login_required
@roles_required("admin")
def index():
    """List all system configuration overrides."""
    overrides = SystemConfigService.get_all()
    return render_template("admin/system_config/index.html", overrides=overrides, active_page="system_config")


@admin_system_config_bp.route("/create", methods=["GET", "POST"])
@login_required
@roles_required("admin")
@limiter.limit("10 per minute")
def create():
    """Create a new system configuration override."""
    if request.method == "GET":
        return render_template("admin/system_config/create.html", active_page="system_config")
    
    # POST request
    key = request.form.get("key", "").strip()
    value = request.form.get("value", "").strip()
    description = request.form.get("description", "").strip()
    
    if not key:
        flash("Key is required.", "error")
        return redirect(url_for("admin_system_config.create"))
    
    if value is None:
        flash("Value is required.", "error")
        return redirect(url_for("admin_system_config.create"))
    
    # Validate key against allowlist
    try:
        SystemConfigService.validate_key(key)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("admin_system_config.create"))
    
    # Validate value for the key
    try:
        SystemConfigService.validate_value(key, value)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("admin_system_config.create"))
    
    try:
        SystemConfigService.set_override(key=key, value=value, description=description)
        flash(f"Override '{key}' set successfully.", "success")
        return redirect(url_for("admin_system_config.index"))
    except Exception as e:
        flash(f"Error setting override: {str(e)}", "error")
        return redirect(url_for("admin_system_config.create"))


@admin_system_config_bp.route("/edit/<key>", methods=["GET", "POST"])
@login_required
@roles_required("admin")
@limiter.limit("10 per minute")
def edit(key: str):
    """Edit an existing system configuration override."""
    override = SystemConfigService.get_by_key(key)
    if override is None:
        flash(f"Override '{key}' not found.", "error")
        return redirect(url_for("admin_system_config.index"))
    
    if request.method == "GET":
        return render_template(
            "admin/system_config/edit.html",
            key=override["key"],
            value=override["value"],
            description=override["description"] or "",
            active_page="system_config"
        )
    
    # POST request
    value = request.form.get("value", "").strip()
    description = request.form.get("description", "").strip()
    
    if value is None:
        flash("Value is required.", "error")
        return redirect(url_for("admin_system_config.edit", key=key))
    
    # Validate value for the key
    try:
        SystemConfigService.validate_value(key, value)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("admin_system_config.edit", key=key))
    
    try:
        SystemConfigService.set_override(key=key, value=value, description=description)
        flash(f"Override '{key}' updated successfully.", "success")
        return redirect(url_for("admin_system_config.index"))
    except Exception as e:
        flash(f"Error updating override: {str(e)}", "error")
        return redirect(url_for("admin_system_config.edit", key=key))


@admin_system_config_bp.route("/delete/<key>", methods=["POST"])
@login_required
@roles_required("admin")
@limiter.limit("5 per minute")
def delete(key: str):
    """Delete a system configuration override."""
    try:
        SystemConfigService.delete_override(key)
        flash(f"Override '{key}' deleted successfully.", "success")
    except Exception as e:
        flash(f"Error deleting override: {str(e)}", "error")
    return redirect(url_for("admin_system_config.index"))