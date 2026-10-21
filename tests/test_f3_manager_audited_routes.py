"""F3: managers must get 200 (not 500) on audited manager-allowed routes.

Root cause: ``audit_admin_action`` hard-checked ``current_user.role != "admin"``
while sitting innermost under ``@write_roles_required`` (admin+manager) on 14
routes — a manager passed the route gate, then hit ``PermissionError`` (500)
and no audit row was written.

Contract pinned here: the decorator's ``roles`` argument must be equal to or
broader than the route's authorization gate.  ``roles=WRITE_ROLES`` on the 14
write-role routes, default ``("admin",)`` everywhere else, exactly one audit
row per invocation either way.

Auth: session keys injected directly (``/auth/login`` is rate-limited 10/min
and the full suite exhausts it first).  Direct-session clients carry no
``session_token``, so the lenient session-validity path applies — these tests
prove RBAC + audit, not session validity.
"""
from __future__ import annotations

import io
import uuid

import pytest
from flask_login.utils import _create_identifier

from app.database import get_cursor
from app.repositories import UserRepository

# (route, expected CSV header prefix, audit action) — headers mirror
# tests/test_admin_export_streaming_route.py
EXPORTS = [
    ("/admin/export/products", b"SKU,Product", "admin.export.products"),
    ("/admin/export/inventory", b"SKU,Product", "admin.export.inventory"),
    ("/admin/export/movements", b"ID,SKU", "admin.export.movements"),
    ("/admin/export/suppliers", b"ID,Name", "admin.export.suppliers"),
    ("/admin/export/purchase_orders", b"ID,PO Number", "admin.export.purchase_orders"),
]

# Only rows created by the routes under test are ever deleted.
_AUDITED_PREFIXES = ("admin.export.%", "admin.data_import.%", "admin.audit_report.%")


def _session_client(app, username: str):
    """Authenticated test client without POSTing /auth/login (capture pattern
    from tests/test_admin_nav_menu.py)."""
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
        sess["_user_id"] = str(_uid(app, username))
        sess["_fresh"] = True
        sess["_id"] = ident_box["id"]
    return c


def _uid(app, username: str) -> int:
    with app.app_context():
        user = UserRepository.find_by_username(username)
        assert user is not None, f"missing user {username}"
        return user.id


def _mark(app) -> int:
    """Audit-log watermark — never blanket-delete the table."""
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(id), 0) AS m FROM audit_log")
            return int(cur.fetchone()["m"])


def _rows(app, mark: int, user_id: int, action: str) -> list[dict]:
    with app.app_context():
        with get_cursor() as cur:
            cur.execute(
                "SELECT * FROM audit_log WHERE id > %s AND user_id = %s AND action = %s"
                " ORDER BY id",
                (mark, user_id, action),
            )
            return list(cur.fetchall())


def _purge(app, mark: int, user_id: int) -> None:
    if user_id is None:
        return
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "DELETE FROM audit_log WHERE id > %s AND user_id = %s AND ("
                "action LIKE %s OR action LIKE %s OR action LIKE %s)",
                (mark, user_id, *_AUDITED_PREFIXES),
            )


@pytest.fixture()
def manager(app):
    return _session_client(app, "manager")


@pytest.fixture()
def viewer(app):
    return _session_client(app, "viewer")


# ── manager: hub pages ────────────────────────────────────────────────

def test_manager_export_hub_200_and_audited(app, manager):
    mark = _mark(app)
    uid = _uid(app, "manager")
    try:
        resp = manager.get("/admin/export/", buffered=True)
        assert resp.status_code == 200
        rows = _rows(app, mark, uid, "admin.export.list")
        assert len(rows) == 1, f"expected 1 audit row, got {len(rows)}"
        assert rows[0]["target_type"] == "export"
    finally:
        _purge(app, mark, uid)


def test_manager_data_import_hub_200_and_audited(app, manager):
    mark = _mark(app)
    uid = _uid(app, "manager")
    try:
        resp = manager.get("/admin/data-import/", buffered=True)
        assert resp.status_code == 200
        rows = _rows(app, mark, uid, "admin.data_import.list")
        assert len(rows) == 1, f"expected 1 audit row, got {len(rows)}"
        assert rows[0]["target_type"] == "data_import"
    finally:
        _purge(app, mark, uid)


def test_manager_audit_report_index_200_and_audited(app, manager):
    mark = _mark(app)
    uid = _uid(app, "manager")
    try:
        resp = manager.get("/admin/audit_reports/", buffered=True)
        assert resp.status_code == 200
        rows = _rows(app, mark, uid, "admin.audit_report.list")
        assert len(rows) == 1, f"expected 1 audit row, got {len(rows)}"
        assert rows[0]["target_type"] == "audit_report"
    finally:
        _purge(app, mark, uid)


# ── manager: CSV downloads ────────────────────────────────────────────

@pytest.mark.parametrize("route,header,action", EXPORTS)
def test_manager_export_download_200_and_audited(app, manager, route, header, action):
    mark = _mark(app)
    uid = _uid(app, "manager")
    try:
        resp = manager.get(route, buffered=True)
        assert resp.status_code == 200, f"{route} -> {resp.status_code}"
        assert resp.mimetype == "text/csv"
        assert ".csv" in resp.headers.get("Content-Disposition", "")
        assert resp.data.startswith(header), f"{route}: bad header {resp.data[:40]!r}"

        rows = _rows(app, mark, uid, action)
        assert len(rows) == 1, f"{route}: expected 1 audit row, got {len(rows)}"
        assert rows[0]["target_type"] == "export"
    finally:
        _purge(app, mark, uid)


def test_manager_export_streams_outside_context(app, manager):
    """F-V1 stream_with_context must survive the roles change (drain with no
    ambient app/request context)."""
    mark = _mark(app)
    uid = _uid(app, "manager")
    try:
        resp = manager.get("/admin/export/products", buffered=False)
        assert resp.status_code == 200
        body = b"".join(resp.response)  # no app/request context here
        assert body.startswith(b"SKU,Product"), body[:40]
    finally:
        _purge(app, mark, uid)


# ── manager: POSTs ────────────────────────────────────────────────────

def test_manager_data_import_upload_audited(app, manager):
    mark = _mark(app)
    uid = _uid(app, "manager")
    wh_name = f"F3-WH-{uuid.uuid4().hex[:10]}"
    csv_data = f"warehouse_name,location\n{wh_name},F3 City\n".encode()
    try:
        resp = manager.post(
            "/admin/data-import/upload/warehouses",
            data={"csv_file": (io.BytesIO(csv_data), "f3_warehouses.csv")},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        assert resp.status_code == 302, f"expected redirect, got {resp.status_code}"

        rows = _rows(app, mark, uid, "admin.data_import.upload")
        assert len(rows) == 1, f"expected 1 audit row, got {len(rows)}"
        assert rows[0]["target_type"] == "data_import"
        assert rows[0]["detail"]["entity"] == "warehouses"

        # 302 + one audit row look identical for an accepted import and a
        # silent rejection (detail_func hides the default detail), so prove
        # the row landed.
        with app.app_context():
            with get_cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM warehouses WHERE warehouse_name = %s", (wh_name,)
                )
                assert cur.fetchone() is not None
    finally:
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM warehouses WHERE warehouse_name = %s", (wh_name,))
        _purge(app, mark, uid)


def test_manager_audit_report_create_get_200(app, manager):
    mark = _mark(app)
    uid = _uid(app, "manager")
    try:
        resp = manager.get("/admin/audit_reports/create", buffered=True)
        assert resp.status_code == 200
    finally:
        _purge(app, mark, uid)


def test_manager_audit_report_create_post_audited(app, manager):
    """Empty name -> flash + redirect; limiter + detail_func stack still audits
    exactly once and creates no report row."""
    mark = _mark(app)
    uid = _uid(app, "manager")
    try:
        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM scheduled_audit_reports")
                before = int(cur.fetchone()["c"] or 0)

        resp = manager.post(
            "/admin/audit_reports/create", data={"name": ""}, follow_redirects=False
        )
        assert resp.status_code == 302, f"expected redirect, got {resp.status_code}"

        rows = _rows(app, mark, uid, "admin.audit_report.create")
        assert len(rows) == 1, f"expected 1 audit row, got {len(rows)}"
        assert rows[0]["target_type"] == "audit_report"
        assert "name" in (rows[0]["detail"] or {})

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM scheduled_audit_reports")
                assert int(cur.fetchone()["c"] or 0) == before
    finally:
        _purge(app, mark, uid)


# ── negative cases (decorator order / gates) ──────────────────────────

@pytest.mark.parametrize(
    "route",
    ["/admin/export/", "/admin/data-import/", "/admin/audit_reports/"],
)
def test_viewer_forbidden(app, viewer, route):
    assert viewer.get(route, buffered=True).status_code == 403


def test_anonymous_export_redirects_to_login(app):
    resp = app.test_client().get("/admin/export/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers.get("Location", "")


# ── admin regression: rows unchanged, still exactly one per action ────

@pytest.mark.parametrize("route,header,action", EXPORTS)
def test_admin_export_download_200_and_audited(app, route, header, action):
    admin_client = _session_client(app, "admin")
    mark = _mark(app)
    uid = _uid(app, "admin")
    try:
        resp = admin_client.get(route, buffered=True)
        assert resp.status_code == 200, f"{route} -> {resp.status_code}"
        assert resp.data.startswith(header)

        rows = _rows(app, mark, uid, action)
        assert len(rows) == 1, f"{route}: expected 1 audit row, got {len(rows)}"
    finally:
        _purge(app, mark, uid)


def test_default_decorator_still_admin_only(app):
    """A bare @audit_admin_action (no roles=) must keep rejecting managers."""
    from flask_login import login_user

    from app.security.audit import audit_admin_action

    with app.app_context():
        manager_user = UserRepository.find_by_username("manager")
        assert manager_user is not None

        @audit_admin_action("admin.action", target_type="admin")
        def admin_only_func():
            return "should not run"

        with app.test_request_context():
            login_user(manager_user)
            with pytest.raises(PermissionError):
                admin_only_func()
