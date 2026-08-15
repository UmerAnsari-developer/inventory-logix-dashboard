"""Input validation helpers used by forms and API endpoints."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

SKU_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9\-_]{1,49}$")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]{3,60}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SAFE_TEXT_PATTERN = re.compile(r"^[\w\s\.\,\-\:\(\)\&\#\/\%\$\@\+]{0,500}$")


class ValidationError(ValueError):
    """Raised when validation fails. Returned as a user-facing message."""


def validate_sku(value: str) -> str:
    if not value or not SKU_PATTERN.match(value.strip().upper()):
        raise ValidationError("SKU must be 2-50 chars: A-Z, 0-9, dash or underscore.")
    return value.strip().upper()


def validate_positive_number(value, name: str = "value", allow_zero: bool = True) -> float:
    try:
        number = float(value)
    except (TypeError, InvalidOperation):
        raise ValidationError(f"{name} must be numeric.")
    if number < 0:
        raise ValidationError(f"{name} cannot be negative.")
    if not allow_zero and number == 0:
        raise ValidationError(f"{name} must be greater than zero.")
    return round(number, 4)


def validate_integer(value, name: str = "value", minimum: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} must be an integer.")
    if number < minimum:
        raise ValidationError(f"{name} must be >= {minimum}.")
    return number


def validate_string_length(value: str, name: str, minimum: int = 1, maximum: int = 200) -> str:
    if value is None:
        raise ValidationError(f"{name} is required.")
    cleaned = value.strip()
    if len(cleaned) < minimum:
        raise ValidationError(f"{name} must be at least {minimum} characters.")
    if len(cleaned) > maximum:
        raise ValidationError(f"{name} must be at most {maximum} characters.")
    return cleaned


def validate_email(value: str) -> str:
    if not value or not EMAIL_PATTERN.match(value.strip()):
        raise ValidationError("Enter a valid email address.")
    return value.strip().lower()


def validate_username(value: str) -> str:
    if not value or not USERNAME_PATTERN.match(value.strip()):
        raise ValidationError(
            "Username must be 3-60 chars using letters, digits, dot, dash or underscore."
        )
    return value.strip().lower()


def validate_password_strength(value: str) -> str:
    if not value or len(value) < 8:
        raise ValidationError("Password must be at least 8 characters long.")
    if len(value) > 128:
        raise ValidationError("Password must be at most 128 characters.")
    if not re.search(r"[A-Za-z]", value):
        raise ValidationError("Password must contain at least one letter.")
    if not re.search(r"\d", value):
        raise ValidationError("Password must contain at least one digit.")
    return value


def sanitize_input(value: str) -> str:
    """Best-effort sanitiser for free-text fields rendered through Jinja auto-escape."""
    if value is None:
        return ""
    return str(value).strip()
