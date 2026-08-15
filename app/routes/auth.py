"""Authentication blueprint — login, register, logout."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import limiter
from ..services import AuthService
from ..services.auth_service import AuthError

auth_bp = Blueprint("auth", __name__, url_prefix="/auth", template_folder="../templates")


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(_role_home(current_user.role))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not request.form.get("remember"):
            flash("Please tick the Remember me checkbox to continue.", "error")
            return render_template("auth/login.html", username=username), 400
        try:
            user = AuthService.authenticate(username, password, ip=request.remote_addr)
        except AuthError as exc:
            flash(str(exc), "error")
            return render_template("auth/login.html", username=username), 401
        login_user(user, remember=True)
        flash(f"Welcome back, {user['username']}!", "success")
        return redirect(_role_home(user["role"]))
    return render_template("auth/login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def register():
    if current_user.is_authenticated:
        return redirect(url_for("ui.dashboard"))
    if request.method == "POST":
        payload = {
            "username": request.form.get("username", ""),
            "email": request.form.get("email", ""),
            "password": request.form.get("password", ""),
            "role": request.form.get("role", "viewer"),
        }
        try:
            AuthService.register(**payload)
        except AuthError as exc:
            flash(str(exc), "error")
            return render_template("auth/register.html", form=payload), 400
        flash("Account created — please log in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form={})


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("ui.dashboard"))


def _role_home(role: str) -> str:
    """Return the role-appropriate main page used after login."""
    return {
        "admin": url_for("ui.dashboard"),
        "manager": url_for("ui.inventory"),
        "viewer": url_for("ui.reports"),
    }.get(role, url_for("ui.dashboard"))
