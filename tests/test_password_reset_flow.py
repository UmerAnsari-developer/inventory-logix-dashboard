"""F-V2: password reset flow against the naive-TIMESTAMP reset-token table.

Pre-fix bugs pinned here (``app/services/auth_service.py``):

* L282 stores ``_utcnow() + timedelta(...)`` (aware) into
  ``sp_reset_token_create(p_expires_at TIMESTAMP)`` → psycopg2 raises
  ``UndefinedFunction`` (no implicit timestamptz→timestamp for function
  resolution) → every forgot-password POST 500s.
* L319 compares the naive DB column with aware ``_utcnow()`` → TypeError.

These tests use a throwaway user per test; the seeded admin account is
never touched (``auth_client`` and many other suites depend on it).
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.database import get_cursor
from app.repositories import UserRepository
from app.services.auth_service import AuthError, AuthService
from app.services.mailer import Mailer

OLD_PASSWORD = "OldPass@123"
NEW_PASSWORD = "NewPass@456"


def _naive_utcnow():
    """Naive-UTC 'now' matching what psycopg2 returns for TIMESTAMP columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def throwaway_user(app):
    """Fresh viewer account; removed again in teardown (audit → tokens → rate → user)."""
    username = f"pwreset_{uuid.uuid4().hex[:12]}"
    email = f"{username}@example.test"
    with app.app_context():
        user_id = AuthService.register(username, email, OLD_PASSWORD, role="viewer")
    yield {"id": user_id, "username": username, "email": email, "password": OLD_PASSWORD}
    with app.app_context():
        with get_cursor(commit=True) as cur:
            # audit_log.user_id is ON DELETE RESTRICT → must go first.
            cur.execute("DELETE FROM audit_log WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM password_reset_tokens WHERE user_id = %s", (user_id,))
            cur.execute(
                "DELETE FROM rate_limit_state WHERE key = %s",
                (f"login:{username}",),
            )
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))


@pytest.fixture
def captured_mail(monkeypatch):
    """Capture the reset link instead of sending mail (SMTP-unconfigured dev path)."""
    captured: dict[str, str] = {}

    def fake_send(to_email, username, reset_link):
        captured["to_email"] = to_email
        captured["link"] = reset_link
        return False

    monkeypatch.setattr(
        "app.services.mailer.Mailer.send_password_reset", staticmethod(fake_send)
    )
    return captured


def _request_reset(client, email):
    response = client.post("/auth/forgot-password", data={"email": email})
    assert response.status_code == 200
    return response


def _active_session_count(app, user_id):
    with app.app_context():
        with get_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM user_sessions WHERE user_id = %s AND is_active",
                (user_id,),
            )
            return cur.fetchone()["n"]


def test_forgot_password_http_creates_naive_utc_token(app, client, throwaway_user, captured_mail):
    _request_reset(client, throwaway_user["email"])

    link = captured_mail["link"]
    assert link.endswith(f"/auth/reset-password/{link.rsplit('/', 1)[-1]}")
    assert "/auth/reset-password/" in link
    token = link.rsplit("/", 1)[-1]

    with app.app_context():
        with get_cursor() as cur:
            cur.execute(
                "SELECT token_hash, expires_at, used FROM password_reset_tokens WHERE user_id = %s",
                (throwaway_user["id"],),
            )
            rows = cur.fetchall()

    assert len(rows) == 1, "exactly one reset token per request (purge-then-create)"
    row = rows[0]
    assert row["expires_at"].tzinfo is None, "column is naive TIMESTAMP — must stay naive"
    assert row["expires_at"] > _naive_utcnow()
    assert row["token_hash"] == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert row["used"] is False


def test_full_reset_flow_rotates_password_and_consumes_token(app, client, throwaway_user, captured_mail):
    _request_reset(client, throwaway_user["email"])
    token = captured_mail["link"].rsplit("/", 1)[-1]

    assert client.get(f"/auth/reset-password/{token}").status_code == 200

    response = client.post(
        f"/auth/reset-password/{token}",
        data={"password": NEW_PASSWORD, "confirm": NEW_PASSWORD},
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]

    with app.test_request_context("/auth/login", method="POST"):
        with pytest.raises(AuthError):
            AuthService.authenticate(throwaway_user["username"], OLD_PASSWORD)
        user = AuthService.authenticate(throwaway_user["username"], NEW_PASSWORD)
        assert user["username"] == throwaway_user["username"]

    with app.app_context():
        with get_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM password_reset_tokens WHERE user_id = %s",
                (throwaway_user["id"],),
            )
            assert cur.fetchone()["n"] == 0, "token must be consumed/purged"

    # Reusing the consumed link must not show the form again.
    reused = client.get(f"/auth/reset-password/{token}")
    assert reused.status_code == 302
    assert "/auth/forgot-password" in reused.headers["Location"]


def test_expired_token_raises_clean_autherror_not_typeerror(app, monkeypatch, throwaway_user):
    """Defence-in-depth: the SP already filters expired rows, so fake one in."""
    expired_row = {
        "id": 10**9,
        "user_id": throwaway_user["id"],
        "token_hash": "0" * 64,
        "expires_at": _naive_utcnow() - timedelta(minutes=10),
        "used": False,
    }
    monkeypatch.setattr(
        UserRepository, "find_valid_reset_token", lambda token_hash: expired_row
    )

    with app.test_request_context():
        with pytest.raises(AuthError, match="expired"):
            AuthService.reset_password("any-token", NEW_PASSWORD)


def test_forged_host_cannot_poison_reset_link(client, throwaway_user, captured_mail):
    """Security gate: Host header is validated before the reset link is built."""
    response = client.post(
        "/auth/forgot-password",
        data={"email": throwaway_user["email"]},
        headers={"Host": "evil.example"},
    )
    assert response.status_code == 400
    assert captured_mail == {}, "forged Host must be rejected before any mail is sent"


def test_mailer_fallback_log_omits_reset_link(app, caplog, monkeypatch):
    """SMTP-unconfigured fallback must not log the live token."""
    monkeypatch.setitem(app.config, "SMTP_HOST", "")
    monkeypatch.setitem(app.config, "SENDGRID_API_KEY", "")
    link = "http://localhost/auth/reset-password/SUPERSECRETTOKEN"
    with app.test_request_context():
        with caplog.at_level(logging.WARNING):
            assert (
                Mailer.send_password_reset("victim@example.test", "victim", link)
                is False
            )
    assert "SUPERSECRETTOKEN" not in caplog.text
    assert "victim@example.test" in caplog.text


# ── F2: password reset / admin revoke must invalidate live sessions ──────────

def test_reset_password_revokes_live_session(app, throwaway_user, captured_mail):
    victim = app.test_client()
    login = victim.post(
        "/auth/login",
        data={"username": throwaway_user["username"], "password": OLD_PASSWORD},
    )
    assert login.status_code == 302
    # Pre-state (anti-false-green): this cookie really authenticates pre-reset.
    assert victim.get("/inventory").status_code == 200

    # Separate cookie jar: the reset route redirects authenticated users away.
    reset_client = app.test_client()
    _request_reset(reset_client, throwaway_user["email"])
    token = captured_mail["link"].rsplit("/", 1)[-1]
    reset = reset_client.post(
        f"/auth/reset-password/{token}",
        data={"password": NEW_PASSWORD, "confirm": NEW_PASSWORD},
    )
    assert reset.status_code == 302

    evicted = victim.get("/inventory")
    assert evicted.status_code == 302
    assert "/auth/login" in evicted.headers["Location"]
    assert _active_session_count(app, throwaway_user["id"]) == 0


def test_reset_then_login_with_new_password_still_works(
    app, throwaway_user, captured_mail
):
    reset_client = app.test_client()
    _request_reset(reset_client, throwaway_user["email"])
    token = captured_mail["link"].rsplit("/", 1)[-1]
    assert (
        reset_client.post(
            f"/auth/reset-password/{token}",
            data={"password": NEW_PASSWORD, "confirm": NEW_PASSWORD},
        ).status_code
        == 302
    )

    client = app.test_client()
    login = client.post(
        "/auth/login",
        data={"username": throwaway_user["username"], "password": NEW_PASSWORD},
    )
    assert login.status_code == 302
    assert client.get("/inventory").status_code == 200


def test_delete_sessions_for_user_evicts_live_cookie(app, throwaway_user):
    victim = app.test_client()
    assert (
        victim.post(
            "/auth/login",
            data={"username": throwaway_user["username"], "password": OLD_PASSWORD},
        ).status_code
        == 302
    )
    # Pre-state (anti-false-green): logged in before the revocation.
    assert victim.get("/inventory").status_code == 200

    # throwaway_user only: its teardown removes the audit rows the
    # trg_session_end trigger writes when sessions are revoked.
    with app.app_context():
        UserRepository.delete_sessions_for_user(throwaway_user["id"])

    evicted = victim.get("/inventory")
    assert evicted.status_code == 302
    assert "/auth/login" in evicted.headers["Location"]


def test_legacy_cookie_without_token_is_allowed(app, throwaway_user):
    from flask_login.utils import _create_identifier

    client = app.test_client()
    box: dict = {}

    def _capture():
        box["id"] = _create_identifier()

    app.before_request_funcs.setdefault(None, []).append(_capture)
    try:
        assert client.get("/static/img/favicon.svg").status_code == 200
    finally:
        app.before_request_funcs[None].remove(_capture)

    with client.session_transaction() as sess:
        sess["_user_id"] = str(throwaway_user["id"])
        sess["_fresh"] = True
        # _id is mandatory: strong session protection wipes the cookie without it.
        sess["_id"] = box["id"]

    assert client.get("/inventory").status_code == 200
