"""Authentication service."""
from __future__ import annotations

import hashlib
import logging
import math
import secrets
import threading
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from flask import current_app

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


def _utcnow() -> datetime:
    """Single clock seam for lockout/reset expiry. Naive UTC to match TIMESTAMP columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ponytail: single-process lockout store — ceiling: workers>1 multiplies threshold per worker; shared store (Redis) DEFERRED with trigger workers>1 or instances>1 (orchestrator decision)
# In-memory failed-login tracker: {user_id: [(timestamp, ip), ...]}
_failed_logins: dict[int, list[tuple[datetime, str | None]]] = defaultdict(list)
# Guards _user_locks create/lookup ONLY — never held during bcrypt/DB work.
_lockout_mutex = threading.Lock()
# Per-user locks: prune → gate → verify → append/clear is one atomic section.
_user_locks: dict[int, threading.Lock] = {}


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

        # Per-user lock: create/lookup under master, release master, then
        # hold the per-user lock across prune → gate → verify → append/clear
        # so concurrent attempts for one user serialize (closes the TOCTOU).
        # Lock ordering: master only guards the dict; only one per-user lock
        # is ever held at a time → no deadlock.
        uid = user["id"]
        with _lockout_mutex:
            user_lock = _user_locks.setdefault(uid, threading.Lock())

        locked_minutes = None
        failed = False
        with user_lock:
            cutoff = _utcnow() - timedelta(minutes=LOCKOUT_MINUTES)
            attempts = _failed_logins[uid]
            # Prune old attempts
            _failed_logins[uid] = attempts = [a for a in attempts if a[0] > cutoff]
            if len(attempts) >= MAX_FAILED_ATTEMPTS:
                remaining = int((attempts[0][0] + timedelta(minutes=LOCKOUT_MINUTES) - _utcnow()).total_seconds()) + 1
                locked_minutes = max(1, math.ceil(remaining / 60))
            elif UserRepository.verify_password(password, user["password_hash"]):
                # Clear failed attempts on success
                _failed_logins.pop(uid, None)
            else:
                _failed_logins[uid].append((_utcnow(), ip))
                failed = True

        # ponytail: audit + bcrypt-adjacent raise happen OUTSIDE the per-user
        # lock — no DB roundtrip while holding it (closes Issue-02 residual).
        if locked_minutes is not None:
            AuditRepository.record(uid, "user.account_locked", target_type="user", target_id=uid, ip_address=ip)
            LOGGER.warning("Lockout for user %s (ip=%s)", username, ip)
            raise AuthError(f"Account locked. Try again in {locked_minutes} minutes.")

        if failed:
            AuditRepository.record(user["id"], "user.login_failed",
                                   target_type="user", target_id=user["id"], ip_address=ip)
            raise AuthError("Invalid username or password.")

        UserRepository.record_login(user["id"])
        AuditRepository.record(user["id"], "user.login",
                               target_type="user", target_id=user["id"], ip_address=ip)
        # Create session tracking record
        session_token = UserRepository.create_session(user["id"], ip, user_agent)
        user.session_token = session_token
        # No remember cookie: only the browser-session cookie is set, so
        # closing the browser always ends the login. The route calls
        # login_user() itself — do NOT call it here (duplicate session write).
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
        expires_at = _utcnow() + timedelta(minutes=ttl)

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
        if row["expires_at"] <= _utcnow():
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
