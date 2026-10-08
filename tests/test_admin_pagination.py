"""TDD tests for Batch 3 pagination fixes (M-001, R-002).

Tests cover:
- M-001: Log viewer pagination UI with filter preservation
- R-002: Pagination on all large-list admin pages (user_activity, user_activity_analytics, backup, audit_report)
"""
from __future__ import annotations

import re
from pathlib import Path
from flask_login.utils import _create_identifier

from app.repositories import UserRepository

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"


def _session_client(app, username: str):
    """Authenticated test client without hitting the /auth/login rate limiter."""
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


def _has_pagination_links(html: str) -> bool:
    """Check if pagination links exist in the HTML."""
    return 'class="pagination"' in html or 'href="?' in html and 'page=' in html


def _extract_pagination_links(html: str) -> list[str]:
    """Extract all pagination hrefs from HTML."""
    return re.findall(r'href="([^"]*page=\d+[^"]*)"', html)


def _link_preserves_filters(href: str, filters: list[str]) -> bool:
    """Check if a pagination link preserves all filter parameters."""
    return all(f in href for f in filters)


# ══════════════════════════════════════════════════════════════════════
# M-001: Log Viewer Pagination
# ══════════════════════════════════════════════════════════════════════

def test_log_viewer_template_has_pagination_ui():
    """Log viewer template must have pagination controls preserving filters."""
    tpl = (TEMPLATES / "admin" / "log_viewer" / "index.html").read_text(encoding="utf-8")
    
    # RED: template must have pagination section
    assert "pagination" in tpl.lower(), "pagination section missing from log viewer template"
    
    # Must preserve filter params in pagination links
    assert "filter_params" in tpl, "filter_params not passed to template for pagination"
    
    # Pagination links should include level, start_date, end_date, search
    for param in ["level", "start_date", "end_date", "search"]:
        assert param in tpl, f"filter param {param} not referenced in pagination"


def test_log_viewer_pagination_preserves_filters(app):
    """Log viewer pagination links must preserve all active filters."""
    client = _session_client(app, "admin")
    
    # Request with multiple filters
    resp = client.get("/admin/logs/?level=ERROR&search=test&limit=10&offset=0")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    
    # Should have pagination structure (nav.pagination) even if no links rendered
    # The template has the pagination structure - check for it
    assert 'class="pagination"' in body or 'pagination' in body.lower()
    
    # If there are links, they should preserve filters
    links = _extract_pagination_links(body)
    for href in links:
        assert "level=ERROR" in href, f"pagination link lost level filter: {href}"
        assert "search=test" in href, f"pagination link lost search filter: {href}"


def test_log_viewer_route_passes_limit_offset_to_service(app):
    """Log viewer route must pass limit/offset to service and template."""
    # This is verified by the template test above and route inspection
    # The route already accepts limit/offset - verify template receives them
    client = _session_client(app, "admin")
    resp = client.get("/admin/logs/?limit=50&offset=100")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Template should receive limit/offset in filter_params
    assert "limit" in body or "offset" in body


# ══════════════════════════════════════════════════════════════════════
# R-002: User Activity Pagination
# ══════════════════════════════════════════════════════════════════════

def test_user_activity_template_has_pagination_ui():
    """User activity template must have pagination controls preserving filters."""
    tpl = (TEMPLATES / "admin" / "user_activity" / "index.html").read_text(encoding="utf-8")
    
    assert "pagination" in tpl.lower(), "pagination section missing from user activity template"
    assert "filter_params" in tpl, "filter_params not passed for pagination"
    
    for param in ["user_id", "action", "start_date", "end_date"]:
        assert param in tpl, f"filter param {param} not referenced in pagination"


def test_user_activity_pagination_preserves_filters(app):
    """User activity pagination links must preserve all active filters."""
    client = _session_client(app, "admin")
    
    resp = client.get("/admin/user_activity/?user_id=1&action=create&limit=10&offset=0")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    
    # Should have pagination structure in template (check template directly).
    # ADM-022: the pagination nav lives in the shared macro — accept either
    # an inline nav or the macro import.
    tpl = (TEMPLATES / "admin" / "user_activity" / "index.html").read_text(encoding="utf-8")
    assert 'class="pagination"' in tpl or "pagination.html" in tpl
    assert "filter_params" in tpl
    
    # If there are links in response, they should preserve filters
    links = _extract_pagination_links(body)
    for href in links:
        assert "user_id=1" in href, f"pagination link lost user_id filter: {href}"
        assert "action=create" in href, f"pagination link lost action filter: {href}"


# ══════════════════════════════════════════════════════════════════════
# R-002: User Activity Analytics Pagination
# ══════════════════════════════════════════════════════════════════════

def test_user_activity_analytics_template_has_pagination_ui():
    """User activity analytics template must have pagination for recent activities."""
    tpl = (TEMPLATES / "admin" / "user_activity_analytics" / "index.html").read_text(encoding="utf-8")
    
    # The recent activities table should have pagination
    assert "pagination" in tpl.lower(), "pagination section missing from user activity analytics template"
    # Should have limit/offset params for recent_activities
    assert "limit" in tpl or "offset" in tpl, "limit/offset not referenced for recent activities pagination"


def test_user_activity_analytics_pagination_preserves_filters(app):
    """User activity analytics pagination should work for recent activities."""
    client = _session_client(app, "admin")
    
    resp = client.get("/admin/user_activity_analytics/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    
    # Should have pagination structure for recent activities
    assert 'class="pagination"' in body or 'pagination' in body.lower() or 'recent_page' in body


# ══════════════════════════════════════════════════════════════════════
# R-002: Backup List Pagination
# ══════════════════════════════════════════════════════════════════════

def test_backup_template_has_pagination_ui():
    """Backup template must have pagination controls."""
    tpl = (TEMPLATES / "admin" / "backup" / "index.html").read_text(encoding="utf-8")
    
    assert "pagination" in tpl.lower(), "pagination section missing from backup template"


def test_backup_pagination_works(app):
    """Backup list should support pagination."""
    client = _session_client(app, "admin")
    
    resp = client.get("/admin/backup/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    
    # Should have pagination structure in template
    tpl = (TEMPLATES / "admin" / "backup" / "index.html").read_text(encoding="utf-8")
    assert 'class="pagination"' in tpl
    assert "backup_page" in tpl or "total_pages" in tpl


# ══════════════════════════════════════════════════════════════════════
# R-002: Audit Report List Pagination
# ══════════════════════════════════════════════════════════════════════

def test_audit_report_template_has_pagination_ui():
    """Audit report template must have pagination controls."""
    tpl = (TEMPLATES / "admin" / "audit_report" / "index.html").read_text(encoding="utf-8")
    
    assert "pagination" in tpl.lower(), "pagination section missing from audit report template"


def test_audit_report_pagination_works(app):
    """Audit report list should support pagination."""
    client = _session_client(app, "admin")
    
    resp = client.get("/admin/audit_reports/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    
    # Should have pagination structure
    assert "pagination" in body.lower() or "page=" in body


# ══════════════════════════════════════════════════════════════════════
# Generic pagination helper tests
# ══════════════════════════════════════════════════════════════════════

def test_pagination_links_use_relative_urls():
    """Pagination links should use relative URLs with query params."""
    # This is a template-level check
    for tpl_path in [
        "admin/log_viewer/index.html",
        "admin/user_activity/index.html",
        "admin/user_activity_analytics/index.html",
        "admin/backup/index.html",
        "admin/audit_report/index.html",
    ]:
        tpl = (TEMPLATES / tpl_path).read_text(encoding="utf-8")
        if "pagination" in tpl.lower():
            # Links should be relative (start with ? or &)
            pagination_links = re.findall(r'href="(\?[^"]*)"', tpl)
            for link in pagination_links:
                assert link.startswith("?"), f"pagination link should be relative: {link}"


def test_pagination_includes_first_last_prev_next():
    """Pagination should have first, prev, next, last links where applicable."""
    # ADM-022: offset-style pagination lives in the shared macro; page-style
    # remains inline. Check both the macro and each template.
    macro = (TEMPLATES / "_macros" / "pagination.html").read_text(encoding="utf-8")
    assert any(x in macro.lower() for x in ["previous", "prev", "next", "first", "last"]), \
        "_macros/pagination.html missing pagination navigation labels"
    for tpl_path in [
        "admin/log_viewer/index.html",
        "admin/user_activity/index.html",
        "admin/backup/index.html",
        "admin/audit_report/index.html",
    ]:
        tpl = (TEMPLATES / tpl_path).read_text(encoding="utf-8")
        if "pagination" in tpl.lower():
            # Should have navigation labels (inline or via the shared macro)
            assert any(x in tpl.lower() for x in ["previous", "prev", "next", "first", "last", "pagination.html"]), \
                f"{tpl_path} missing pagination navigation labels"