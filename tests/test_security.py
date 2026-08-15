"""Tests for security helpers and validators."""
from __future__ import annotations

import pytest

from app.security.validators import (
    validate_email,
    validate_integer,
    validate_password_strength,
    validate_positive_number,
    validate_sku,
    validate_string_length,
    validate_username,
    ValidationError,
)


def test_validate_sku_ok():
    assert validate_sku("SKU-TECH-001") == "SKU-TECH-001"


def test_validate_sku_rejects_invalid():
    with pytest.raises(ValidationError):
        validate_sku("sku tech 001")


def test_validate_email():
    assert validate_email("me@example.com") == "me@example.com"
    with pytest.raises(ValidationError):
        validate_email("not-an-email")


def test_validate_username():
    assert validate_username("admin") == "admin"
    with pytest.raises(ValidationError):
        validate_username("a!")


def test_password_strength():
    with pytest.raises(ValidationError):
        validate_password_strength("short")
    with pytest.raises(ValidationError):
        validate_password_strength("nodigitshere")
    pw = validate_password_strength("Strong1Pass")
    assert pw == "Strong1Pass"


def test_validate_positive_number_zero_allowed():
    assert validate_positive_number(0) == 0.0


def test_validate_positive_number_zero_disallowed_raises():
    with pytest.raises(ValidationError):
        validate_positive_number(0, allow_zero=False)


def test_validate_positive_number_positive_when_zero_disallowed():
    assert validate_positive_number(5, allow_zero=False) == 5.0


def test_validate_positive_number_rounds_four_decimals():
    assert validate_positive_number(1.23456) == 1.2346


def test_validate_integer_boundary_at_minimum():
    assert validate_integer(5, minimum=5) == 5
    with pytest.raises(ValidationError):
        validate_integer(4, minimum=5)


def test_validate_string_length_minimum_boundary():
    assert validate_string_length("a", "x") == "a"
    with pytest.raises(ValidationError):
        validate_string_length("", "x")


def test_validate_string_length_maximum_boundary():
    value = "a" * 200
    assert validate_string_length(value, "x") == value
    with pytest.raises(ValidationError):
        validate_string_length(value + "a", "x")


def test_password_strength_length_boundaries():
    pw8 = validate_password_strength("Short1A9")
    assert pw8 == "Short1A9"
    with pytest.raises(ValidationError):
        validate_password_strength("Short1")
    long_ok = "A1" * 64
    assert validate_password_strength(long_ok) == long_ok
    with pytest.raises(ValidationError):
        validate_password_strength("A1" * 64 + "A")


def test_security_headers_present(client):
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Content-Security-Policy")


def test_login_rate_limit(client):
    # A couple of requests should not trip the rate limiter immediately.
    for _ in range(3):
        response = client.post(
            "/auth/login",
            data={"username": "x", "password": "y", "remember": "on"},
        )
        assert response.status_code in (401, 429)
