"""Authentication service."""
from __future__ import annotations

import logging

from flask_login import login_user

from ..repositories import UserRepository, AuditRepository
from ..security.validators import (
    ValidationError,
    validate_email,
    validate_password_strength,
    validate_username,
)

LOGGER = logging.getLogger(__name__)


class AuthError(Exception):
    """Domain-level authentication error."""


class AuthService:
    """Register, authenticate, and audit users."""

    @staticmethod
    def register(username: str, email: str, password: str, role: str = "viewer") -> int:
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
        if role not in {"admin", "manager", "viewer"}:
            role = "viewer"

        user_id = UserRepository.create(username, email, password, role)
        AuditRepository.record(user_id, "user.register", target_type="user", target_id=user_id)
        return user_id

    @staticmethod
    def authenticate(username: str, password: str, ip: str | None = None):
        user = UserRepository.find_by_username(username)
        if not user or not user.get("is_active"):
            raise AuthError("Invalid username or password.")
        if not UserRepository.verify_password(password, user["password_hash"]):
            AuditRepository.record(user["id"], "user.login_failed",
                                   target_type="user", target_id=user["id"], ip_address=ip)
            raise AuthError("Invalid username or password.")
        UserRepository.record_login(user["id"])
        AuditRepository.record(user["id"], "user.login",
                               target_type="user", target_id=user["id"], ip_address=ip)
        login_user(user, remember=True)
        return user
