"""Admin user management routes."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.security import write_roles_required, roles_required
from app.repositories import UserRepository

admin_user_management_bp = Blueprint(
    "admin_user_management", __name__, url_prefix="/admin/users"
)


@admin_user_management_bp.route("/")
@login_required
@roles_required("admin")
def index():
    """List all users."""
    users = UserRepository.list_all()
    return render_template(
        "admin/user_management/index.html", users=users, active_page="user_management"
    )


@admin_user_management_bp.route("/create", methods=["GET", "POST"])
@login_required
@roles_required("admin")
def create():
    """Create a new user."""
    if request.method == "GET":
        return render_template(
            "admin/user_management/create.html", active_page="user_management"
        )

    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()
    role = request.form.get("role", "viewer").strip()

    if not username or not email or not password:
        flash("Username, email, and password are required.", "error")
        return redirect(url_for("admin_user_management.create"))

    if role not in ("admin", "manager", "viewer"):
        flash("Invalid role.", "error")
        return redirect(url_for("admin_user_management.create"))

    try:
        UserRepository.create(username=username, email=email, password=password, role=role)
        flash(f"User '{username}' created successfully.", "success")
        return redirect(url_for("admin_user_management.index"))
    except Exception as e:
        flash(f"Error creating user: {e}", "error")
        return redirect(url_for("admin_user_management.create"))


@admin_user_management_bp.route("/edit/<int:user_id>", methods=["GET", "POST"])
@login_required
@roles_required("admin")
def edit(user_id: int):
    """Edit a user (change role, toggle active)."""
    user = UserRepository.find_by_id(user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("admin_user_management.index"))

    if request.method == "GET":
        return render_template(
            "admin/user_management/edit.html",
            user=user,
            active_page="user_management",
        )

    role = request.form.get("role", user.get("role", "viewer")).strip()
    is_active = request.form.get("is_active") == "on"
    new_password = request.form.get("password", "").strip()

    if role not in ("admin", "manager", "viewer"):
        flash("Invalid role.", "error")
        return redirect(url_for("admin_user_management.edit", user_id=user_id))

    try:
        UserRepository.change_role(user_id, role)
        UserRepository.set_active(user_id, is_active)
        if new_password:
            UserRepository.set_password(user_id, new_password)
            flash("User password updated.", "success")
        flash(f"User '{user.get('username')}' updated successfully.", "success")
        return redirect(url_for("admin_user_management.index"))
    except Exception as e:
        flash(f"Error updating user: {e}", "error")
        return redirect(url_for("admin_user_management.edit", user_id=user_id))


@admin_user_management_bp.route("/toggle/<int:user_id>", methods=["POST"])
@login_required
@roles_required("admin")
def toggle_active(user_id: int):
    """Toggle a user's active status."""
    user = UserRepository.find_by_id(user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("admin_user_management.index"))

    try:
        new_status = not user.get("is_active", True)
        UserRepository.set_active(user_id, new_status)
        status_word = "activated" if new_status else "deactivated"
        flash(f"User '{user.get('username')}' {status_word}.", "success")
    except Exception as e:
        flash(f"Error toggling user status: {e}", "error")

    return redirect(url_for("admin_user_management.index"))


@admin_user_management_bp.route("/change-role/<int:user_id>", methods=["POST"])
@login_required
@roles_required("admin")
def change_role(user_id: int):
    """Quick-change a user's role from the list view."""
    user = UserRepository.find_by_id(user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("admin_user_management.index"))

    role = request.form.get("role", "").strip()
    if role not in ("admin", "manager", "viewer"):
        flash("Invalid role.", "error")
        return redirect(url_for("admin_user_management.index"))

    try:
        UserRepository.change_role(user_id, role)
        flash(f"User '{user.get('username')}' role changed to {role}.", "success")
    except Exception as e:
        flash(f"Error changing role: {e}", "error")

    return redirect(url_for("admin_user_management.index"))
