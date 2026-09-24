"""TDD tests: Administration menubar lists the 8 admin pages + dashboard 500.

Spec (user-approved menu, labels corrected against actual page titles):
  1  Backup & Restore           /admin/backup/               admin-only
  2  Data Import Hub            /admin/data-import/          write roles
  3  System Config              /admin/system_config/        admin-only
  4  User Activity Analytics    /admin/user_activity_analytics/  write roles
  5  User Management            /admin/users/                admin-only
  6  Log Viewer                 /admin/logs/                 write roles
  7  Notification Center        /admin/notifications/        write roles
  8  Data Export                /admin/export/               write roles
  +  Settings (existing sole entry)                          write roles

Role split mirrors the routes: roles_required("admin") vs
write_roles_required (admin+manager).  Test 4 pins the /admin/dashboard/
500 (route called a module-level get_dashboard_data that never existed).

Auth: session keys injected directly — /auth/login is rate-limited 10/min
and the full suite exhausts it before this file runs (repo convention).
"""
from __future__ import annotations

# (label, href, admin_only) — hrefs verified against blueprint url_prefixes
MENU_ITEMS = [
    ("Backup & Restore", "/admin/backup/", True),
    ("Data Import Hub", "/admin/data-import/", False),
    ("System Config", "/admin/system_config/", True),
    ("User Activity Analytics", "/admin/user_activity_analytics/", False),
    ("User Management", "/admin/users/", True),
    ("Log Viewer", "/admin/logs/", False),
    ("Notification Center", "/admin/notifications/", False),
    ("Data Export", "/admin/export/", False),
]


def _session_client(app, username: str):
    """Authenticated test client without POSTing /auth/login (10/min cap).

    Sets the Flask-Login session keys login_user() would, including the
    strong session-protection identifier captured from a real request so
    IP/User-Agent hashing matches (copied repo pattern).
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


def test_admin_menu_lists_all_eight_pages(app):
    body = _session_client(app, "admin").get("/").get_data(as_text=True)
    assert "Administration" in body
    assert "Settings" in body, "existing Settings entry must stay"
    missing = [
        f"{label} ({href})"
        for label, href, _ in MENU_ITEMS
        if href not in body or label not in body
    ]
    assert missing == [], f"Administration menu missing: {missing}"


def test_manager_menu_hides_admin_only_pages(app):
    body = _session_client(app, "manager").get("/").get_data(as_text=True)
    assert "Administration" in body, "manager keeps the section"
    for label, href, admin_only in MENU_ITEMS:
        if admin_only:
            assert label not in body, f"manager must not see {label}"
            assert href not in body, f"manager must not see {href}"
        else:
            assert label in body, f"manager should see {label}"
            assert href in body, f"manager should see {href}"


def test_viewer_has_no_administration_section(app):
    body = _session_client(app, "viewer").get("/").get_data(as_text=True)
    assert "Administration" not in body
    for label, href, _ in MENU_ITEMS:
        assert label not in body, f"viewer must not see {label}"
        assert href not in body, f"viewer must not see {href}"


def test_admin_dashboard_page_renders(app):
    """GET /admin/dashboard/ must be 200 (was 500: AttributeError)."""
    resp = _session_client(app, "admin").get("/admin/dashboard/")
    assert resp.status_code == 200, (
        f"expected 200, got {resp.status_code}: "
        f"{resp.get_data(as_text=True)[:300]}"
    )
