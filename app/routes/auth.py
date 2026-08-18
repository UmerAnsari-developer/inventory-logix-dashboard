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
        remember = bool(request.form.get("remember"))
        try:
            user = AuthService.authenticate(username, password, ip=request.remote_addr)
        except AuthError as exc:
            flash(str(exc), "error")
            return render_template("auth/login.html", username=username), 401
        login_user(user, remember=remember)
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
        }
        try:
            AuthService.register(**payload, role="viewer")
        except AuthError as exc:
            flash(str(exc), "error")
            return render_template("auth/register.html", form=payload), 400
        flash("Account created — you are signed up as a Viewer. Please log in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form={})


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per hour")
def forgot_password():
    if current_user.is_authenticated:
        return redirect(_role_home(current_user.role))
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        try:
            result = AuthService.request_password_reset(
                email, host_url=request.host_url, ip=request.remote_addr
            )
        except AuthError as exc:
            flash(str(exc), "error")
            return render_template("auth/forgot_password.html", email=email), 400
        flash(
            "If an account exists for that email, a reset link has been sent.",
            "info",
        )
        return render_template(
            "auth/forgot_password.html",
            email="",
            reset_link=result.get("reset_link") or "",
        )
    return render_template("auth/forgot_password.html", email="", reset_link="")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    if current_user.is_authenticated:
        return redirect(_role_home(current_user.role))
    if request.method == "POST":
        new_password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if new_password != confirm:
            flash("Passwords do not match.", "error")
            return render_template(
                "auth/reset_password.html", token=token
            ), 400
        try:
            AuthService.reset_password(token, new_password, ip=request.remote_addr)
        except AuthError as exc:
            flash(str(exc), "error")
            return render_template(
                "auth/reset_password.html", token=token
            ), 400
        flash("Password updated — please log in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset_password.html", token=token)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("ui.dashboard"))


def _role_home(role: str) -> str:
    """Return the role-appropriate main page used after login."""
    return url_for("ui.dashboard")
