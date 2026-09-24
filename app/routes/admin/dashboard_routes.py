"""Admin dashboard routes."""
from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.security import write_roles_required
from app.services import admin_dashboard_service

admin_dashboard_bp = Blueprint("admin_dashboard", __name__, url_prefix="/admin/dashboard")


@admin_dashboard_bp.route("/")
@login_required
@write_roles_required
def index():
    """Admin dashboard."""
    try:
        data = admin_dashboard_service.AdminDashboardService.get_dashboard_data()
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("ui.dashboard"))
    return render_template(
        "admin/dashboard/index.html",
        data=data,
        active_page="dashboard"
    )