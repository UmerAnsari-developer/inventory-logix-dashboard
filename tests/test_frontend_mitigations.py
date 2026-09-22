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


# ══════════════════════════════════════════════════════════════════════
# Batch 2 — Tasks 5+6 (session-handler.js, http-client.js, base.html,
# main.js offline/online listeners). Verification suite for shipped code;
# each test embeds RED evidence against a known-bad sample.
# ══════════════════════════════════════════════════════════════════════

STATIC_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js"
SESSION_HANDLER_JS = STATIC_JS / "session-handler.js"
HTTP_CLIENT_JS = STATIC_JS / "http-client.js"


def _has_batch2_assets(html: str) -> bool:
    """Shared checker for the authenticated-page asset contract."""
    return (
        "js/session-handler.js?v=" in html
        and "js/http-client.js?v=" in html
        and "window.LOGIN_URL" in html
        and "/auth/login" in html
    )


# ── Batch 2 Test 1: new scripts + LOGIN_URL on authenticated pages ─────

def test_session_and_http_scripts_included(app):
    # RED evidence: a page without the Batch 2 assets fails this checker
    assert not _has_batch2_assets("<html><body>old page</body></html>")

    body = _session_client(app, "admin").get("/").get_data(as_text=True)
    assert "js/session-handler.js?v=" in body, "session-handler.js not included"
    assert "js/http-client.js?v=" in body, "http-client.js not included"
    assert "window.LOGIN_URL" in body, "LOGIN_URL bootstrap missing"
    assert 'window.LOGIN_URL = "/auth/login"' in body, "LOGIN_URL value wrong"
    assert _has_batch2_assets(body)


# ── Batch 2 Test 2: LOGIN_URL absent on the login page ──────────────────

def test_login_url_absent_on_login_page(app):
    # /auth/login is rate-limited 10/min for GET+POST; earlier suite tests
    # exhaust it (see test_security_headers_present baseline failure).
    # Reset shared limiter state so this test is order-independent —
    # assertions below are unchanged.
    from app.extensions import limiter

    limiter.reset()
    resp = app.test_client().get("/auth/login")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "window.LOGIN_URL" not in body, (
        "LOGIN_URL must live in the authenticated-only block"
    )


# ── Batch 2 Test 3: no Jinja braces leaked into static JS ───────────────

def test_static_js_has_no_jinja_braces():
    # RED evidence: detection finds the plan's known bug pattern in a bad sample
    bad = 'href = "{{ url_for(\'auth.login\') }}"'
    assert "{{" in bad

    for path in (SESSION_HANDLER_JS, HTTP_CLIENT_JS):
        text = path.read_text(encoding="utf-8")
        assert "{{" not in text, f"Jinja braces leaked into {path.name}"


# ── Batch 2 Test 4: timeoutId declared before try (block-scope bug) ─────

def test_http_client_retry_scoping():
    text = HTTP_CLIENT_JS.read_text(encoding="utf-8")

    # RED evidence: same ordering check fails on a snippet that declares
    # timeoutId AFTER the try/finally that clears it (the plan's bug)
    bad = (
        "for (let attempt = 0; attempt <= maxRetries; attempt++) {\n"
        "  try {\n"
        "    timeoutId = setTimeout(fn, timeout);\n"
        "  } finally {\n"
        "    clearTimeout(timeoutId);\n"
        "  }\n"
        "}\n"
        "let timeoutId;\n"
    )
    assert bad.index("try {") < bad.index("let timeoutId"), (
        "bad sample must FAIL the ordering the real file must pass"
    )

    decl = text.index("let timeoutId")
    try_idx = text.index("try {")
    assert decl < try_idx, (
        "timeoutId must be declared before the try that uses it "
        "(block-scope ReferenceError in finally)"
    )
    assert "finally" in text, "timeout cleanup finally block missing"


# ── Batch 2 Test 5: GET/HEAD retry=2, other methods retry=0 ─────────────

def test_http_client_retry_policy():
    text = HTTP_CLIENT_JS.read_text(encoding="utf-8")
    # Actual implementation notation: method === 'GET' || method === 'HEAD' ? 2 : 0
    assert "(method === 'GET' || method === 'HEAD' ? 2 : 0)" in text, (
        "default retry policy (GET/HEAD=2, others=0) missing"
    )
    # Retries are opt-out per call: explicit retries overrides the default
    assert "retries != null" in text


# ── Batch 2 Test 6: main.js online/offline listeners + T7 no-regress ────

def test_main_js_offline_listeners():
    text = MAIN_JS.read_text(encoding="utf-8")
    assert 'addEventListener("offline"' in text, "offline listener missing"
    assert 'addEventListener("online"' in text, "online listener missing"
    # T7 guard must survive the Batch 2 append
    assert "submitting.has(form)" in text, "T7 duplicate-submit guard lost"


# ── Batch 2 Test 7: no Jinja AND no url_for strings in static JS ────────

def test_no_jinja_in_new_script():
    # RED evidence: url_for detector fires on a crafted bad snippet
    bad = 'fetch("{{ url_for(\'ui.dashboard\') }}")'
    assert re.search(r"url_for", bad)

    for path in (SESSION_HANDLER_JS, HTTP_CLIENT_JS):
        text = path.read_text(encoding="utf-8")
        assert "{{" not in text, f"Jinja braces in {path.name}"
        assert re.search(r"url_for", text) is None, (
            f"url_for string leaked into {path.name}"
        )


# ── Batch 2 Test 8: new Headers(...) never built from null ─────────────

def test_http_client_headers_init_never_null():
    # RED evidence: the pre-fix line trips the same check the gate applies
    def bad_headers_line(line: str) -> bool:
        return "new Headers(" in line and "null" in line

    bad_line = "const headers = new Headers(fetchOptions.headers || null);"
    assert bad_headers_line(bad_line), (
        "detector must flag `new Headers(... || null)` (HeadersInit has no null)"
    )

    text = HTTP_CLIENT_JS.read_text(encoding="utf-8")
    header_lines = [ln for ln in text.splitlines() if "new Headers(" in ln]
    assert header_lines, "new Headers(...) construction missing from http-client.js"
    offenders = [ln for ln in header_lines if "null" in ln]
    assert offenders == [], f"new Headers built from null in: {offenders}"
    # Fixed form present: `|| {}` (current file) or direct pass-through
    assert any(("|| {}" in ln) or ("new Headers(fetchOptions.headers)" in ln)
               for ln in header_lines), (
        "headers must default with `|| {}` or pass through directly"
    )


# ══════════════════════════════════════════════════════════════════════
# Batch 3 — Tasks 10, 11, 14, 17.
# ══════════════════════════════════════════════════════════════════════

STYLE_CSS = Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "style.css"


# ── T10: pagination links preserve filter query params ─────────────────

def test_inventory_pagination_preserves_filters(app):
    client = _session_client(app, "manager")
    # search=a matches 112 of 118 seeded products -> 6 pages, real next link.
    # (search=cable matches 0 rows: no pagination links render, vacuous pass.)
    resp = client.get("/inventory?search=a&page=1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # RED evidence: the pre-fix markup drops every filter
    assert 'href="?page=2"' not in body, "bare ?page= link still drops filters"
    assert 'href="?page=1"' not in body, "bare ?page= link still drops filters"
    import re as _re
    next_match = _re.search(r'href="([^"]*page=2[^"]*)"', body)
    assert next_match, "no pagination link to page 2 found (test not vacuous)"
    href = next_match.group(1)
    assert "search=a" in href, f"next-page link lost the search filter: {href}"
    assert "page=2" in href, f"next-page link lost page param: {href}"


# ── T11: destructive forms carry data-confirm ──────────────────────────

def test_destructive_forms_have_data_confirm():
    # RED evidence: an unguarded destructive form fails the same checker
    def has_guard(form_html: str) -> bool:
        return (
            "data-confirm=" in form_html
            or "onsubmit=" in form_html
            or "confirm(" in form_html
        )

    assert not has_guard(
        '<form method="post" action="/admin/backup/1/restore"></form>'
    ), "checker must flag an unguarded destructive form"

    # Every destructive form must be guarded
    destructive_actions = (
        "admin_data_import.upload",       # CSV import overwrites data
        "ui.monitoring_run_etl",          # warehouse rebuild
        "admin_user_management.edit",     # can deactivate/reset password
        "ui.delete_supplier",             # existing inline onsubmit
        "admin_backup.restore",           # existing inline onclick
        "admin_backup.delete",            # existing inline onclick
        "admin_system_config.delete",     # existing inline onclick
        "notification_center.delete_notification",  # existing inline onclick
        "admin_audit_report.delete",      # existing inline onclick
        "ui.update_po_status",            # existing inline onchange confirm
        "admin_user_management.change_role",  # existing inline onchange confirm
        "admin_user_management.toggle_active",  # existing inline onclick confirm
    )
    offenders = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for action in destructive_actions:
            if f"url_for('{action}" not in text:
                continue
            # Extract each <form ...>...</form> block containing this action
            for m in __import__("re").finditer(
                r"<form\b[^>]*url_for\('" + __import__("re").escape(action)
                + r"'[^>]*>.*?</form>",
                text,
                __import__("re").S,
            ):
                if not has_guard(m.group(0)):
                    offenders.append(f"{path.relative_to(TEMPLATES)}::{action}")
    assert offenders == [], f"destructive forms missing confirm: {offenders}"

    # The shared data-confirm mechanism must still exist in main.js
    js = MAIN_JS.read_text(encoding="utf-8")
    assert 'form[data-confirm]' in js, "data-confirm submit listener removed"
    assert "confirm(msg)" in js


# ── T14: .table-responsive horizontal scroll rule ──────────────────────

def test_table_responsive_rule_exists():
    # RED evidence: pre-fix CSS has the class nowhere
    bad_css = ".table-scroll { overflow-x: auto; }"
    assert ".table-responsive" not in bad_css

    text = STYLE_CSS.read_text(encoding="utf-8")
    import re as _re
    rule = _re.search(r"\.table-responsive\s*\{[^}]*\}", text)
    assert rule, ".table-responsive rule missing from style.css"
    assert "overflow-x: auto" in rule.group(0), (
        ".table-responsive must enable horizontal scrolling"
    )


# ── T17: filter bar z-index regression guard ───────────────────────────

def test_filter_bar_zindex_regression_guard():
    import re as _re

    # RED evidence: removing the property trips the same guard
    def rule_body(css: str, selector: str) -> str:
        import re as _re
        m = _re.search(_re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert m, f"{selector} rule missing"
        return m.group(1)

    bad = ".filter-bar { position: relative; }"
    assert "z-index: 30" not in bad
    assert "z-index: 30" in rule_body(
        ".filter-bar { position: relative; z-index: 30; }", ".filter-bar"
    )

    text = STYLE_CSS.read_text(encoding="utf-8")
    for selector in (".filter-bar", ".report-filter-row"):
        # .filter-bar is declared twice (base layout + glass override at
        # L3658); the z-index lives in the later rule. Scan every match.
        bodies = [
            m.group(1)
            for m in _re.finditer(_re.escape(selector) + r"\s*\{([^}]*)\}", text)
        ]
        assert bodies, f"{selector} rule missing"
        combined = "\n".join(bodies)
        assert "position: relative" in combined, (
            f"{selector} lost position: relative (dropdown trap regression)"
        )
        assert "z-index: 30" in combined, (
            f"{selector} lost z-index: 30 (dropdown trap regression)"
        )


# ── Fix-round: PO status select declarative confirm (CSP-dead onchange) ─

def test_po_status_select_no_inline_handlers():
    # RED evidence: the not-contains detector fires on the old inline pattern
    bad = '<select name="status" onchange="this.form.submit()">'
    assert "onchange" in bad, "detector must trip on the pre-fix sample"
    good = '<select name="status" data-confirm-value="cancelled">'
    assert "onchange" not in good

    text = (TEMPLATES / "purchase_orders.html").read_text(encoding="utf-8")
    assert "onchange" not in text, (
        "inline onchange is CSP-dead (nonce-only script-src, no "
        "script-src-attr) and must stay gone"
    )
    assert 'data-confirm-value="cancelled"' in text, (
        "declarative confirm value missing from PO status select"
    )
    assert 'data-confirm="Cancel this purchase order?"' in text, (
        "confirm message missing from PO status select"
    )


# ── Fix-round: main.js select[data-confirm-value] handler + T11 no-regress ─

def test_main_js_select_confirm_handler():
    text = MAIN_JS.read_text(encoding="utf-8")
    assert 'select[data-confirm-value]' in text, (
        "select confirm-value change handler missing"
    )
    assert "requestSubmit" in text, (
        "requestSubmit() (with .submit() fallback) missing"
    )
    # T11 form-level listener must survive this fix round
    assert 'form[data-confirm]' in text, "T11 data-confirm submit listener lost"
    assert "confirm(msg)" in text


# ── Fix-round: base.html main.js cache-bust bump ───────────────────────

def test_main_js_version_bumped():
    text = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    # url_for emits: js/main.js') }}?v=1.5 — match across the quote/brace gap
    assert re.search(r"main\.js[')\s}{]*\?v=1\.5", text), (
        "base.html must reference main.js?v=1.5 (handler change needs bust)"
    )
