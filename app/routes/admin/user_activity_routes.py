"""Admin user activity monitoring routes."""
from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.security import write_roles_required
from app.services import UserActivityService

from app.database import get_cursor
admin_user_activity_bp = Blueprint("admin_user_activity", __name__, url_prefix="/admin/user_activity")


@admin_user_activity_bp.route("/")
@login_required
@write_roles_required
def index():
    """List user activities with optional filtering."""
    # Get filter parameters from query string
    user_id = request.args.get("user_id", type=int)
    action = request.args.get("action", type=str)
    start_date = request.args.get("start_date", type=str)
    end_date = request.args.get("end_date", type=str)
    limit = request.args.get("limit", default=100, type=int)
    offset = request.args.get("offset", default=0, type=int)
    
    activities = UserActivityService.get_activities(
        limit=limit, offset=offset, user_id=user_id,
        action=action, start_date=start_date, end_date=end_date
    )
    
    total_count = UserActivityService.get_activities_count(
        user_id=user_id, action=action, start_date=start_date, end_date=end_date
    )
    
    # Get list of users for the filter dropdown (only admins/managers can see all users)
    users_list = []
    if current_user.role in ("admin", "manager"):
        from app.repositories import UserRepository
        with get_cursor() as cur:
            cur.execute("SELECT id, username FROM users ORDER BY username")
            users_list = [dict(row) for row in cur.fetchall()]
    
    # Get the user's username for display
    from app.repositories import UserRepository
    user = UserRepository.find_by_id(user_id)
    username = user["username"] if user else f"User {user_id}"
    
    return render_template(
        "admin/user_activity/index.html",
        activities=activities,
        total_count=total_count,
        users=users_list,
        filter_params={
            "user_id": user_id,
            "action": action,
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
            "offset": offset
        },
        active_page="user_activity"
    )


@admin_user_activity_bp.route("/user/<int:user_id>")
@login_required
@write_roles_required
def user_activities(user_id: int):
    """List activities for a specific user."""
    activities = UserActivityService.get_activities_by_user(user_id=user_id, limit=100)
    
    # Get the user's username for display
    from app.repositories import UserRepository
    user = UserRepository.find_by_id(user_id)
    username = user["username"] if user else f"User {user_id}"
    
    return render_template(
        "admin/user_activity/user.html",
        activities=activities,
        username=username,
        user_id=user_id,
        active_page="user_activity"
    )
