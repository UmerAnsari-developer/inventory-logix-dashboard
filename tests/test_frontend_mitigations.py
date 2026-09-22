"""TDD tests for Batch 1 frontend mitigations (Tasks 1-4, 7-9).

Each test proves one mitigation from
docs/superpowers/plans/2026-09-22-frontend-issue-mitigation-plan.md:
  1  Task 4  no empty catch blocks swallowing errors (incl. RED-proof samples)
  2  Task 1  notification templates render (list + detail)
  3  Task 2  admin-only nav links hidden from non-admin roles
  4  Task 3  activityChart.getContext guarded by null check
  5  Task 7  duplicate-submit guard in main.js
  6  Task 8  novalidate forms validated by main.js
  7  Task 9  aria-invalid wiring + clear-on-input in main.js

Auth note: HTTP login is rate-limited to 10/min, which the full suite
exhausts before this file runs. These tests inject the Flask-Login
session keys directly instead of POSTing /auth/login.
"""
from __future__ import annotations

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"
MAIN_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "main.js"

# Matches a JS catch clause with an empty body: catch(e){} / catch (e) {}
EMPTY_CATCH = re.compile(r"catch\s*\(\s*\w*\s*\)\s*\{\s*\}")


def _session_client(app, username: str):
    """Authenticated test client without hitting the /auth/login rate limiter.

    Sets the same Flask-Login session keys login_user() would, including the
    strong session-protection identifier. The identifier is captured from a
    real request on this client so IP/User-Agent hashing matches exactly.
    """
    from flask_login.utils import _create_identifier

    from app.repositories import UserRepository

    with app.app_context():
        user = UserRepository.find_by_username(username)
        assert user is not None, f"missing user {username}"
        uid = user.id

    c = app.test_client()
    ident_box: dict = {}

    def _capture_ident():
        ident_box["id"] = _create_identifier()

    app.before_request_funcs.setdefault(None, []).append(_capture_ident)
    try:
        resp = c.get("/static/img/favicon.svg")
        assert resp.status_code == 200, "identifier probe request failed"
    finally:
        app.before_request_funcs[None].remove(_capture_ident)
    assert "id" in ident_box, "failed to capture session identifier"

    with c.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
        sess["_id"] = ident_box["id"]
    return c


# ── Test 1 / Task 4: empty catch blocks ────────────────────────────────

def test_no_empty_catch_blocks_in_templates():
    # RED proof: this regex catches the pre-fix patterns the issue reported...
    assert EMPTY_CATCH.search("try { x(); } catch(e){}")
    assert EMPTY_CATCH.search("try { x(); } catch (e) {}")
    assert EMPTY_CATCH.search("try { x(); } catch(err) {\n}")
    # ...but not promise-style .catch(fn) handlers (false-positive guard)
    assert not EMPTY_CATCH.search(".catch(function () {});")

    offenders = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if EMPTY_CATCH.search(text):
            offenders.append(str(path.relative_to(TEMPLATES)))
    assert offenders == [], f"empty catch blocks remain in: {offenders}"


# ── Test 2 / Task 1: notification templates ────────────────────────────

def test_notifications_list_and_detail_render(app):
    client = _session_client(app, "admin")

    # List page renders with heading
    resp = client.get("/notifications")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "<h1>Notifications</h1>" in body

    # Detail page renders a created notification, 404s for unknown id
    with app.app_context():
        from app.repositories import NotificationRepository, UserRepository

        admin = UserRepository.find_by_username("admin")
        assert admin is not None
        notif_id = NotificationRepository.create(
            admin.id, "TDD probe", "frontend mitigation test", "&#9675;", None
        )
    try:
        detail = client.get(f"/notifications/{notif_id}")
        assert detail.status_code == 200
        assert "TDD probe" in detail.get_data(as_text=True)

        missing = client.get("/notifications/99999999")
        assert missing.status_code == 404
    finally:
        with app.app_context():
            from app.repositories import NotificationRepository

            NotificationRepository.delete(notif_id, admin.id)


# ── Test 3 / Task 2: admin-only nav gating ─────────────────────────────

def test_admin_nav_links_hidden_from_non_admin(app):
    # Manager: Administration menu exists, admin-only entries do not
    manager_body = (
        _session_client(app, "manager").get("/").get_data(as_text=True)
    )
    assert "Administration" in manager_body  # manager keeps the section
    assert "User Management" not in manager_body
    assert "Backup & Restore" not in manager_body
    assert "System Configuration" not in manager_body

    # Viewer: no Administration section at all
    viewer_body = _session_client(app, "viewer").get("/").get_data(as_text=True)
    assert "Administration" not in viewer_body
    assert "User Management" not in viewer_body

    # Admin: all three admin-only entries visible
    admin_body = _session_client(app, "admin").get("/").get_data(as_text=True)
    assert "User Management" in admin_body
    assert "Backup & Restore" in admin_body
    assert "System Configuration" in admin_body


# ── Test 4 / Task 3: activityChart null guard ──────────────────────────

def test_activity_chart_getcontext_is_guarded():
    text = (TEMPLATES / "admin" / "user_activity_analytics" / "index.html").read_text(
        encoding="utf-8"
    )
    canvas = text.find("getElementById('activityChart')")
    guard = text.find("if (chartCanvas)")
    getctx = text.find("chartCanvas.getContext")
    assert canvas != -1, "activityChart lookup missing"
    assert guard != -1, "null guard missing before getContext"
    assert getctx != -1, "getContext call missing"
    assert canvas < guard < getctx, "guard must sit between lookup and getContext"


# ── Test 5 / Task 7: duplicate-submit guard ────────────────────────────

def test_main_js_duplicate_submit_guard():
    text = MAIN_JS.read_text(encoding="utf-8")
    assert "new WeakSet()" in text
    assert "submitting.has(form)" in text
    assert "submitting.add(form)" in text
    # Guard must preventDefault before buttons are disabled
    assert text.index("submitting.has(form)") < text.index("submitting.add(form)")


# ── Test 6 / Task 8: novalidate forms validated by JS ──────────────────

def test_main_js_validates_novalidate_forms():
    text = MAIN_JS.read_text(encoding="utf-8")
    assert 'form.hasAttribute("novalidate")' in text
    assert "validateNovalidateForm" in text
    # Every template form that opts out of native validation is covered
    for rel in (
        "auth/register.html",
        "suppliers.html",
        "purchase_orders.html",
        "product_form.html",
    ):
        tpl = (TEMPLATES / rel).read_text(encoding="utf-8")
        assert "novalidate" in tpl, f"{rel} lost its novalidate contract"


# ── Test 7 / Task 9: aria-invalid wiring + clear-on-input ──────────────

def test_main_js_aria_invalid_and_clear_on_input():
    text = MAIN_JS.read_text(encoding="utf-8")
    # Invalid field gets aria-invalid=true and describedby error id
    assert 'setAttribute("aria-invalid", "true")' in text
    assert 'setAttribute("aria-describedby"' in text
    # Valid field clears the state
    assert 'removeAttribute("aria-invalid")' in text
    # Error clears as the user fixes the field (input listener)
    assert 'addEventListener("input"' in text
    input_idx = text.index('addEventListener("input"')
    assert "clearFieldError" in text[input_idx:]
