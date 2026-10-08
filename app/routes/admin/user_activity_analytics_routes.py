"""User activity analytics routes."""
from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.security import write_roles_required
from app.services import UserActivityAnalyticsService

admin_user_activity_analytics_bp = Blueprint("admin_user_activity_analytics", __name__, url_prefix="/admin/user_activity_analytics")


@admin_user_activity_analytics_bp.route("/")
@login_required
@write_roles_required
def index():
    """User activity analytics dashboard."""
    recent_page = request.args.get("recent_page", default=1, type=int)
    recent_limit = 20
    recent_offset = (recent_page - 1) * recent_limit
    
    try:
        # Get various analytics
        activity_counts = UserActivityAnalyticsService.get_activity_counts_by_day(days=30)
        top_users = UserActivityAnalyticsService.get_top_users(limit=10)
        top_actions = UserActivityAnalyticsService.get_top_actions(limit=10)
        recent_activities = UserActivityAnalyticsService.get_recent_activities(limit=recent_limit, offset=recent_offset)
        recent_total = UserActivityAnalyticsService.get_recent_activities_count()
    except Exception as e:
        flash(f"Error loading analytics: {str(e)}", "error")
        return redirect(url_for("ui.dashboard"))
    
    return render_template(
        "admin/user_activity_analytics/index.html",
        activity_counts=activity_counts,
        top_users=top_users,
        top_actions=top_actions,
        recent_activities=recent_activities,
        recent_page=recent_page,
        recent_total=recent_total,
        recent_limit=recent_limit,
        active_page="user_activity_analytics"
    )