"""Admin user management routes with audit logging."""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import limiter
from app.security import write_roles_required, roles_required
from app.security.audit import audit_admin_action
from app.security.validators import validate_password_strength
from app.repositories import UserRepository

admin_user_management_bp = Blueprint(
    "admin_user_management", __name__, url_prefix="/admin/users"
)


@admin_user_management_bp.route("/")
@login_required
@roles_required("admin")
@audit_admin_action("admin.user.list", target_type="user")
def index():
    """List all users."""
    users = UserRepository.list_all()
    return render_template(
        "admin/user_management/index.html", users=users, active_page="user_management"
    )


@admin_user_management_bp.route("/create", methods=["GET", "POST"])
@login_required
@roles_required("admin")
@limiter.limit("10 per minute")
@audit_admin_action("admin.user.create", target_type="user", detail_func=lambda r, *a, **kw: {"username": kw.get("username") or request.form.get("username")})
def create():
    """Create a new user."""
    if request.method == "GET":
        managers = UserRepository.list_managers()
        return render_template(
            "admin/user_management/create.html", active_page="user_management",
            managers=managers,
        )

    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()
    role = request.form.get("role", "viewer").strip()
    full_name = request.form.get("full_name", "").strip() or None
    department = request.form.get("department", "").strip() or None
    job_role = request.form.get("job_role", "").strip() or None
    reporting_manager_id = request.form.get("reporting_manager_id", "").strip() or None

    if not username or not email or not password:
        flash("Username, email, and password are required.", "error")
        return redirect(url_for("admin_user_management.create"))

    if role not in ("admin", "manager", "viewer"):
        flash("Invalid role.", "error")
        return redirect(url_for("admin_user_management.create"))

    # ADM-017/040: enforce the same password policy as self-registration.
    try:
        password = validate_password_strength(password)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_user_management.create"))

    try:
        new_id = UserRepository.create(username=username, email=email, password=password, role=role)
        # Organizational profile (additive fields)
        if full_name or department or job_role:
            UserRepository.update_profile(new_id, full_name=full_name,
                                          department=department, job_role=job_role)
        # Reporting manager (validated: no self, active, no cycle)
        if reporting_manager_id:
            from app.services.user_service import UserService
            try:
                UserService.set_reporting_manager(new_id, int(reporting_manager_id), current_user)
            except ValueError as exc:
                flash(f"User created, but reporting manager not set: {exc}", "warning")
        flash(f"User '{username}' created successfully.", "success")
        return redirect(url_for("admin_user_management.index"))
    except Exception as e:
        flash(f"Error creating user: {e}", "error")
        return redirect(url_for("admin_user_management.create"))


@admin_user_management_bp.route("/edit/<int:user_id>", methods=["GET", "POST"])
@login_required
@roles_required("admin")
@limiter.limit("10 per minute")
@audit_admin_action("admin.user.update", target_type="user", target_id_arg="user_id")
def edit(user_id: int):
    """Edit a user (change role, toggle active)."""
    # Prevent self-modification
    if user_id == current_user.id:
        flash("You cannot modify your own account.", "error")
        return redirect(url_for("admin_user_management.index"))

    user = UserRepository.find_by_id(user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("admin_user_management.index"))

    if request.method == "GET":
        managers = UserRepository.list_managers()
        return render_template(
            "admin/user_management/edit.html",
            user=user,
            managers=managers,
            active_page="user_management",
        )

    # ADM-006: only admins may modify other admins (privilege-escalation guard)
    if user.get("role") == "admin" and current_user.role != "admin":
        abort(403)

    role = request.form.get("role", user.get("role", "viewer")).strip()
    is_active = request.form.get("is_active") == "on"
    new_password = request.form.get("password", "").strip()
    full_name = request.form.get("full_name", "").strip() or None
    department = request.form.get("department", "").strip() or None
    job_role = request.form.get("job_role", "").strip() or None
    reporting_manager_id = request.form.get("reporting_manager_id", "").strip() or None

    if role not in ("admin", "manager", "viewer"):
        flash("Invalid role.", "error")
        return redirect(url_for("admin_user_management.edit", user_id=user_id))

    # ADM-017/040: enforce the same password policy as self-registration.
    if new_password:
        try:
            new_password = validate_password_strength(new_password)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin_user_management.edit", user_id=user_id))

    try:
        UserRepository.change_role(user_id, role)
        UserRepository.set_active(user_id, is_active)
        # ADM-016: invalidate the user's sessions so a demoted/deactivated
        # account loses access immediately instead of at session expiry.
        UserRepository.delete_sessions_for_user(user_id)
        if new_password:
            UserRepository.set_password(user_id, new_password)
            flash("User password updated.", "success")
        # Organizational profile (additive fields)
        UserRepository.update_profile(user_id, full_name=full_name,
                                      department=department, job_role=job_role)
        # Reporting manager (validated: no self, active, no cycle)
        from app.services.user_service import UserService
        try:
            UserService.set_reporting_manager(
                user_id, int(reporting_manager_id) if reporting_manager_id else None,
                current_user,
            )
        except ValueError as exc:
            flash(f"User updated, but reporting manager not set: {exc}", "warning")
        flash(f"User '{user.get('username')}' updated successfully.", "success")
        return redirect(url_for("admin_user_management.index"))
    except Exception as e:
        flash(f"Error updating user: {e}", "error")
        return redirect(url_for("admin_user_management.edit", user_id=user_id))


@admin_user_management_bp.route("/toggle/<int:user_id>", methods=["POST"])
@login_required
@roles_required("admin")
@limiter.limit("20 per minute")
@audit_admin_action("admin.user.toggle_active", target_type="user", target_id_arg="user_id")
def toggle_active(user_id: int):
    """Toggle a user's active status."""
    # Prevent self-deactivation
    if user_id == current_user.id:
        flash("You cannot disable your own account.", "error")
        return redirect(url_for("admin_user_management.index"))

    user = UserRepository.find_by_id(user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("admin_user_management.index"))

    # ADM-006: only admins may modify other admins (privilege-escalation guard)
    if user.get("role") == "admin" and current_user.role != "admin":
        abort(403)

    try:
        new_status = not user.get("is_active", True)
        UserRepository.set_active(user_id, new_status)
        # ADM-016: deactivate the user's sessions immediately.
        UserRepository.delete_sessions_for_user(user_id)
        status_word = "activated" if new_status else "deactivated"
        flash(f"User '{user.get('username')}' {status_word}.", "success")
    except Exception as e:
        flash(f"Error toggling user status: {e}", "error")

    return redirect(url_for("admin_user_management.index"))


@admin_user_management_bp.route("/change-role/<int:user_id>", methods=["POST"])
@login_required
@roles_required("admin")
@limiter.limit("20 per minute")
@audit_admin_action("admin.user.change_role", target_type="user", target_id_arg="user_id")
def change_role(user_id: int):
    """Quick-change a user's role from the list view."""
    # Prevent self-demotion
    if user_id == current_user.id:
        flash("You cannot change your own role.", "error")
        return redirect(url_for("admin_user_management.index"))

    user = UserRepository.find_by_id(user_id)
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for("admin_user_management.index"))

    # ADM-006: only admins may modify other admins (privilege-escalation guard)
    if user.get("role") == "admin" and current_user.role != "admin":
        abort(403)

    role = request.form.get("role", "").strip()
    if role not in ("admin", "manager", "viewer"):
        flash("Invalid role.", "error")
        return redirect(url_for("admin_user_management.index"))

    try:
        UserRepository.change_role(user_id, role)
        # ADM-016: invalidate sessions so the new role takes effect immediately.
        UserRepository.delete_sessions_for_user(user_id)
        flash(f"User '{user.get('username')}' role changed to {role}.", "success")
    except Exception as e:
        flash(f"Error changing role: {e}", "error")

    return redirect(url_for("admin_user_management.index"))