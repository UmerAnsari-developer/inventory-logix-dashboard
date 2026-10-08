"""Authentication service with PostgreSQL-backed rate limiting."""
from __future__ import annotations

import hashlib
import logging
import math
import secrets
import threading
from datetime import datetime, timedelta, timezone

from flask import current_app

from ..repositories import UserRepository, AuditRepository
from ..database import get_cursor
from ..security.validators import (
    ValidationError,
    validate_email,
    validate_password_strength,
    validate_username,
)

LOGGER = logging.getLogger(__name__)

# DB-006 (resolved): lockout counters are shared across workers — persisted in
# the PostgreSQL rate_limit_state table guarded by pg_advisory_lock, so the
# threshold holds with workers>1. Flask-Limiter route limits use Redis
# (RATELIMIT_STORAGE_URI); this per-account lockout stays on PostgreSQL.
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# Issue 02: in-process lockout state (uid → failed-attempt timestamps).
# One threading.Lock spans the gate check → password verify → append/clear so
# N concurrent wrong-password attempts can never exceed MAX_FAILED_ATTEMPTS
# (fixes the TOCTOU where gate, append, and clear sat in separate critical
# sections with bcrypt verify in between). rate_limit_state (below) remains
# the cross-worker persistence layer.
# ponytail: single global lock serializes all logins in-process; per-user
# locks if login throughput ever matters.
_failed_logins: dict[int, list[datetime]] = {}
_failed_logins_lock = threading.Lock()


def _utcnow() -> datetime:
    """Single clock seam for lockout/reset expiry. Timezone-aware UTC to match TIMESTAMPTZ columns."""
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    """Normalize naive datetimes to aware UTC (test fake clocks may be naive)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class AuthError(Exception):
    """Domain-level authentication error."""


class AuthService:
    """Register, authenticate, and audit users with PostgreSQL-backed rate limiting."""

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

        try:
            user_id = UserRepository.create(username, email, password, "viewer")
        except Exception as exc:
            # DB-077: catch unique violation from concurrent registration
            from ..security.dberrors import is_unique_violation
            if is_unique_violation(exc):
                raise AuthError("Email is already registered.") from exc
            raise
        AuditRepository.record(user_id, "user.register", target_type="user", target_id=user_id)
        return user_id

    @staticmethod
    def _get_rate_limit_key(username: str) -> str:
        """Generate rate limit key for username."""
        return f"login:{username.lower()}"

    @staticmethod
    def _check_rate_limit(key: str) -> tuple[bool, int | None]:
        """
        Check rate limit in PostgreSQL.
        Returns (is_locked, locked_minutes_remaining).
        Does NOT increment the counter - only checks current state.
        """
        with get_cursor() as cur:
            # Try to acquire advisory lock for this key
            lock_key = hash(key) & 0x7FFFFFFF  # Convert to 32-bit positive int
            cur.execute("SELECT pg_advisory_lock(%s)", (lock_key,))
            
            try:
                now = _as_utc(_utcnow())
                current_window_start = now - timedelta(minutes=LOCKOUT_MINUTES)

                # Get current rate limit state
                cur.execute("""
                    SELECT count, window_start, expires_at
                    FROM rate_limit_state
                    WHERE key = %s
                """, (key,))

                row = cur.fetchone()
                if not row:
                    return False, None

                count = row["count"]
                db_window_start = _as_utc(row["window_start"])
                expires_at = _as_utc(row["expires_at"])

                # Check if window has expired (db_window_start is older than the current window)
                if db_window_start < current_window_start:
                    # Window expired, treat as count = 0 (not locked)
                    count = 0

                # Check if expired
                if expires_at < now:
                    count = 0

                if count >= MAX_FAILED_ATTEMPTS:
                    # Calculate remaining lockout time
                    remaining_seconds = int((expires_at - now).total_seconds()) + 1
                    locked_minutes = max(1, math.ceil(remaining_seconds / 60))
                    return True, locked_minutes

                return False, None
            finally:
                # Release advisory lock
                cur.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))

    @staticmethod
    def _record_failed_attempt(key: str) -> int:
        """Record a failed login attempt atomically. Returns new count."""
        with get_cursor(commit=True) as cur:
            lock_key = hash(key) & 0x7FFFFFFF
            cur.execute("SELECT pg_advisory_lock(%s)", (lock_key,))
            
            try:
                now = _as_utc(_utcnow())
                expires_at = now + timedelta(minutes=LOCKOUT_MINUTES)
                window_cutoff = now - timedelta(minutes=LOCKOUT_MINUTES)

                cur.execute("""
                    INSERT INTO rate_limit_state (key, count, window_start, expires_at, updated_at)
                    VALUES (%s, 1, %s, %s, %s)
                    ON CONFLICT (key) DO UPDATE SET
                        count = CASE 
                            WHEN rate_limit_state.window_start < %s THEN 1
                            ELSE rate_limit_state.count + 1
                        END,
                        window_start = CASE 
                            WHEN rate_limit_state.window_start < %s THEN EXCLUDED.window_start
                            ELSE rate_limit_state.window_start
                        END,
                        expires_at = EXCLUDED.expires_at,
                        updated_at = EXCLUDED.updated_at
                    RETURNING count
                """, (key, now, expires_at, now, window_cutoff, window_cutoff))
                
                row = cur.fetchone()
                return row["count"]
            finally:
                cur.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))

    @staticmethod
    def _clear_rate_limit(key: str) -> None:
        """Clear rate limit on successful login."""
        with get_cursor(commit=True) as cur:
            lock_key = hash(key) & 0x7FFFFFFF
            cur.execute("SELECT pg_advisory_lock(%s)", (lock_key,))
            
            try:
                cur.execute("DELETE FROM rate_limit_state WHERE key = %s", (key,))
            finally:
                cur.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))

    @staticmethod
    def _lockout_error(uid: int, username: str, ip: str | None, minutes: int) -> AuthError:
        """Audit + warn for a lockout trigger, then return the AuthError to raise."""
        AuditRepository.record(uid, "user.account_locked", target_type="user", target_id=uid, ip_address=ip)
        LOGGER.warning("Lockout for user %s (ip=%s)", username, ip)
        return AuthError(f"Account locked. Try again in {minutes} minutes.")

    @staticmethod
    def authenticate(username: str, password: str, ip: str | None = None, user_agent: str | None = None):
        user = UserRepository.find_by_username(username)
        if not user or not user.get("is_active"):
            raise AuthError("Invalid username or password.")
        if not user.get("password_hash"):
            raise AuthError("Invalid username or password.")

        uid = user["id"]
        key = AuthService._get_rate_limit_key(username)

        # Issue 02: ONE critical section spans gate → verify → append/clear so
        # concurrent attempts cannot all pass the gate before any append lands.
        with _failed_logins_lock:
            # ── Gate 1: in-process failed-attempt counter (uid-keyed) ──
            entries = _failed_logins.get(uid)
            if entries:
                now = _as_utc(_utcnow())
                first = _as_utc(entries[0])
                if first < now - timedelta(minutes=LOCKOUT_MINUTES):
                    _failed_logins.pop(uid, None)  # window elapsed → fresh counter
                elif len(entries) >= MAX_FAILED_ATTEMPTS:
                    remaining = max(
                        1,
                        math.ceil(
                            ((first + timedelta(minutes=LOCKOUT_MINUTES)) - now).total_seconds() / 60
                        ),
                    )
                    raise AuthService._lockout_error(uid, username, ip, remaining)

            # ── Gate 2: PostgreSQL counter (cross-worker, DB-006) ──
            is_locked, locked_minutes = AuthService._check_rate_limit(key)
            if is_locked:
                raise AuthService._lockout_error(uid, username, ip, locked_minutes)

            # Verify password (inside the lock → no TOCTOU window)
            if UserRepository.verify_password(password, user["password_hash"]):
                # Clear failed attempts on success
                AuthService._clear_rate_limit(key)
                _failed_logins.pop(uid, None)

                UserRepository.record_login(user["id"])
                AuditRepository.record(user["id"], "user.login", target_type="user", target_id=user["id"], ip_address=ip)

                # Create session tracking record
                session_token = UserRepository.create_session(user["id"], ip, user_agent)
                user.session_token = session_token
                return user
            else:
                # Record failed attempt (both layers, inside the lock)
                AuthService._record_failed_attempt(key)
                _failed_logins.setdefault(uid, []).append(_as_utc(_utcnow()))
                AuditRepository.record(user["id"], "user.login_failed", target_type="user", target_id=user["id"], ip_address=ip)
                raise AuthError("Invalid username or password.")

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