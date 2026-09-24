"""Notification center routes."""
from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.security import write_roles_required
from app.services.nnotification_center_service import NotificationCenterService

notification_center_bp = Blueprint("notification_center", __name__, url_prefix="/admin/notifications")


@notification_center_bp.route("/")
@login_required
@write_roles_required
def index():
    """List notifications for the current user."""
    notifications = NotificationCenterService.list_notifications()
    unread_count = NotificationCenterService.get_unread_count()
    return render_template(
        "admin/notification_center/index.html",
        notifications=notifications,
        unread_count=unread_count,
        active_page="notifications"
    )


@notification_center_bp.route("/mark_read/<int:notification_id>", methods=["POST"])
@login_required
@write_roles_required
def mark_read(notification_id: int):
    """Mark a notification as read."""
    try:
        NotificationCenterService.mark_read(notification_id)
        flash("Notification marked as read.", "success")
    except Exception as e:
        flash(f"Error marking notification as read: {str(e)}", "error")
    return redirect(url_for("notification_center.index"))


@notification_center_bp.route("/mark_all_read", methods=["POST"])
@login_required
@write_roles_required
def mark_all_read():
    """Mark all notifications as read."""
    try:
        NotificationCenterService.mark_all_read()
        flash("All notifications marked as read.", "success")
    except Exception as e:
        flash(f"Error marking all notifications as read: {str(e)}", "error")
    return redirect(url_for("notification_center.index"))


@notification_center_bp.route("/delete/<int:notification_id>", methods=["POST"])
@login_required
@write_roles_required
def delete_notification(notification_id: int):
    """Delete a notification."""
    try:
        NotificationCenterService.delete_notification(notification_id)
        flash("Notification deleted.", "success")
    except Exception as e:
        flash(f"Error deleting notification: {str(e)}", "error")
    return redirect(url_for("notification_center.index"))