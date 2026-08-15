"""Tests for the authentication flow."""
from __future__ import annotations

import pytest


def test_login_page_renders(client):
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert b"Welcome back" in response.data or b"Sign in" in response.data


def test_login_with_invalid_credentials(client):
    response = client.post(
        "/auth/login",
        data={"username": "nope", "password": "wrong", "remember": "on"},
        follow_redirects=True,
    )
    assert response.status_code in (200, 401)
    assert b"Invalid" in response.data or b"nope" in response.data


def test_register_validation(client):
    response = client.post(
        "/auth/register",
        data={"username": "ab", "email": "not-an-email", "password": "short", "role": "viewer"},
        follow_redirects=True,
    )
    assert response.status_code in (200, 400)
    assert b"required" in response.data.lower() or b"invalid" in response.data.lower() or b"valid" in response.data.lower()


def test_protected_route_redirects(client):
    response = client.get("/inventory")
    assert response.status_code in (302, 303)
    assert "/auth/login" in response.headers.get("Location", "")
