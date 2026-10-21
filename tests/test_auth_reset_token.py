"""Tests for password reset token not exposed in UI (H-001).

Repaired: the previous version asserted HTTP 200 on a request for a
nonexistent email — ``AuthService.request_password_reset`` exits early for
unknown emails, so the test passed without ever generating a token (false
green). It also had three assertion-free stubs and a sha256 tautology.

These tests pin the real UI gate in ``app/routes/auth.py`` (``show_reset_link``)
by stubbing the service result and checking the rendered page both ways.
Token generation/hashing itself is covered end-to-end in
``tests/test_password_reset_flow.py``.
"""
from __future__ import annotations

import pytest

from app.services.auth_service import AuthService

SECRET_LINK = "http://localhost/auth/reset-password/SUPERSECRETTOKEN"


def _stub_service(monkeypatch):
    """Service returns an undelivered link (SMTP-unconfigured dev behavior)."""

    def fake_request_password_reset(email, host_url, ip=None):
        return {"delivered": False, "reset_link": SECRET_LINK, "user_found": True}

    monkeypatch.setattr(
        AuthService, "request_password_reset", staticmethod(fake_request_password_reset)
    )


class TestPasswordResetTokenExposure:
    """Test that password reset tokens are not exposed in UI."""

    def test_forgot_password_hides_link_when_debug_gate_disabled(
        self, app, client, monkeypatch
    ):
        """The reset link must not render outside the debug + env-flag gate."""
        monkeypatch.delenv("SHOW_RESET_LINK_IN_UI", raising=False)
        assert app.debug is False, "testing config must not be in debug mode"
        _stub_service(monkeypatch)

        response = client.post(
            "/auth/forgot-password", data={"email": "anyone@example.test"}
        )

        assert response.status_code == 200
        assert b"/auth/reset-password/" not in response.data
        assert b"SUPERSECRETTOKEN" not in response.data

    def test_forgot_password_shows_link_only_when_debug_gate_enabled(
        self, app, client, monkeypatch
    ):
        """With debug + SHOW_RESET_LINK_IN_UI the dev link renders (gate works)."""
        monkeypatch.setattr(app, "debug", True)
        monkeypatch.setenv("SHOW_RESET_LINK_IN_UI", "true")
        _stub_service(monkeypatch)

        response = client.post(
            "/auth/forgot-password", data={"email": "anyone@example.test"}
        )

        assert response.status_code == 200
        assert b"SUPERSECRETTOKEN" in response.data
