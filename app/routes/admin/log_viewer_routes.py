"""Admin system logs viewer routes."""
from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from datetime import datetime

from app.security import write_roles_required
from app.services import LogViewerService

admin_log_viewer_bp = Blueprint("admin_log_viewer", __name__, url_prefix="/admin/logs")


@admin_log_viewer_bp.route("/")
@login_required
@write_roles_required
def index():
    """View system logs with optional filtering."""
    # Get filter parameters from query string
    level = request.args.get("level", type=str)
    start_date_str = request.args.get("start_date", type=str)
    end_date_str = request.args.get("end_date", type=str)
    search = request.args.get("search", type=str)
    limit = request.args.get("limit", default=100, type=int)
    offset = request.args.get("offset", default=0, type=int)
    
    # Convert date strings to datetime objects
    start_date = None
    end_date = None
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        except ValueError:
            flash("Invalid start date format. Use YYYY-MM-DD.", "warning")
            start_date = None
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        except ValueError:
            flash("Invalid end date format. Use YYYY-MM-DD.", "warning")
            end_date = None
    
    log_entries = LogViewerService.get_log_entries(
        limit=limit, offset=offset, level=level,
        start_date=start_date, end_date=end_date, search=search
    )
    
    total_count = LogViewerService.get_log_count()
    
    return render_template(
        "admin/log_viewer/index.html",
        log_entries=log_entries,
        total_count=total_count,
        filter_params={
            "level": level,
            "start_date": start_date_str,
            "end_date": end_date_str,
            "search": search,
            "limit": limit,
            "offset": offset
        },
        active_page="logs"
    )