"""Authentication service."""
from __future__ import annotations

import hashlib
import logging
import secrets
import threading
from datetime import datetime, timedelta
from collections import defaultdict

from flask import current_app
from flask_login import login_user

from ..repositories import UserRepository, AuditRepository
from ..security.validators import (
    ValidationError,
    validate_email,
    validate_password_strength,
    validate_username,
)

LOGGER = logging.getLogger(__name__)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# In-memory failed-login tracker: {user_id: [(timestamp, ip), ...]}
_failed_logins: dict[int, list[tuple[datetime, str | None]]] = defaultdict(list)
_lockout_mutex = threading.Lock()


class AuthError(Exception):
    """Domain-level authentication error."""


class AuthService:
    """Register, authenticate, and audit users."""

    @staticmethod
    def register(username: str, email: str, password: str, role: str = "viewer") -> int:
        """Create a new account. Self-registration is always a viewer."""
        try:
            username = validate_username(username)
            email = validate_email(email)
            password = validate_password_strength(password)
        except ValidationError as exc:
            raise AuthError(str(exc)) from exc

        if UserRepository.find_by_username(username):
            raise AuthError("Username is already taken.")
        if UserRepository.find_by_email(email):
            raise AuthError("Email is already registered.")

        user_id = UserRepository.create(username, email, password, "viewer")
        AuditRepository.record(user_id, "user.register", target_type="user", target_id=user_id)
        return user_id

    @staticmethod
    def authenticate(username: str, password: str, ip: str | None = None, user_agent: str | None = None):
        user = UserRepository.find_by_username(username)
        if not user or not user.get("is_active"):
            raise AuthError("Invalid username or password.")
        if not user.get("password_hash"):
            raise AuthError("Invalid username or password.")

        # Check account lockout
        uid = user["id"]
        cutoff = datetime.utcnow() - timedelta(minutes=LOCKOUT_MINUTES)
        with _lockout_mutex:
            attempts = _failed_logins[uid]
            # Prune old attempts
            _failed_logins[uid] = attempts = [a for a in attempts if a[0] > cutoff]
            if len(attempts) >= MAX_FAILED_ATTEMPTS:
                remaining = int((attempts[0][0] + timedelta(minutes=LOCKOUT_MINUTES) - datetime.utcnow()).total_seconds()) + 1
                raise AuthError(f"Account locked. Try again in {remaining // 60 + 1} minutes.")

        if not UserRepository.verify_password(password, user["password_hash"]):
            with _lockout_mutex:
                _failed_logins[uid].append((datetime.utcnow(), ip))
            AuditRepository.record(user["id"], "user.login_failed",
                                   target_type="user", target_id=user["id"], ip_address=ip)
            raise AuthError("Invalid username or password.")

        # Clear failed attempts on success
        with _lockout_mutex:
            _failed_logins.pop(uid, None)

        UserRepository.record_login(user["id"])
        AuditRepository.record(user["id"], "user.login",
                               target_type="user", target_id=user["id"], ip_address=ip)
        # Create session tracking record
        session_token = UserRepository.create_session(user["id"], ip, user_agent)
        user.session_token = session_token
        from flask_login import login_user
        login_user(user, remember=True)
        return user

    @staticmethod
    def request_password_reset(email: str, host_url: str, ip: str | None = None) -> dict:
        """Generate a reset token for the user with the given email.

        Returns a dict with ``delivered`` (bool, whether an email was sent),
        ``reset_link`` (full URL — only set when SMTP is unconfigured), and
        ``user_found`` (bool — used for auditing).

        The same generic user-visible message is shown regardless of whether
        a matching account exists, to prevent user-enumeration.
        """
        try:
            email = validate_email(email)
        except ValidationError as exc:
            raise AuthError(str(exc)) from exc

        result = {"delivered": False, "reset_link": "", "user_found": False}
        user = UserRepository.find_by_email(email)
        if not user or not user.get("is_active"):
            AuditRepository.record(
                None,
                "user.password_reset_requested_unknown",
                target_type="user",
                detail={"email": email},
                ip_address=ip,
            )
            return result

        result["user_found"] = True
        token_plain = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(token_plain.encode("utf-8")).hexdigest()
        ttl = current_app.config["PASSWORD_RESET_TTL_MINUTES"]
        expires_at = datetime.utcnow() + timedelta(minutes=ttl)

        UserRepository.purge_reset_tokens(user["id"])
        UserRepository.create_reset_token(user["id"], token_hash, expires_at)
        AuditRepository.record(
            user["id"],
            "user.password_reset_requested",
            target_type="user",
            target_id=user["id"],
            ip_address=ip,
        )

        reset_link = f"{host_url.rstrip('/')}/auth/reset-password/{token_plain}"
        from .mailer import Mailer  # local import: avoid SMTP import at startup

        sent = Mailer.send_password_reset(
            user["email"], user["username"], reset_link
        )
        result["delivered"] = sent
        if not sent:
            result["reset_link"] = reset_link
        return result

    @staticmethod
    def reset_password(token: str, new_password: str, ip: str | None = None) -> None:
        """Validate a reset token and apply the new password."""
        try:
            new_password = validate_password_strength(new_password)
        except ValidationError as exc:
            raise AuthError(str(exc)) from exc

        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        row = UserRepository.find_valid_reset_token(token_hash)
        if not row:
            raise AuthError("This reset link is invalid or has already been used.")
        if row["used"]:
            raise AuthError("This reset link has already been used.")
        if row["expires_at"] <= datetime.utcnow():
            raise AuthError("This reset link has expired. Please request a new one.")

        user_id = row["user_id"]
        UserRepository.set_password(user_id, new_password)
        UserRepository.consume_reset_token(row["id"])
        UserRepository.purge_reset_tokens(user_id)
        AuditRepository.record(
            user_id,
            "user.password_reset_completed",
            target_type="user",
            target_id=user_id,
            ip_address=ip,
        )
