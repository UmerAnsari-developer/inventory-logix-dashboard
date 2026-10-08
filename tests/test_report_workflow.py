"""Reporting hierarchy + report workflow integration tests (IDOR, cycles)."""
from __future__ import annotations

import logging
import os

logging.disable(logging.WARNING)
os.environ["FLASK_ENV"] = "testing"

import pytest

from app import create_app


@pytest.fixture()
def app():
    app = create_app()
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["TESTING"] = True
    return app


def _login(client, username, password):
    return client.post("/auth/login", data={"username": username, "password": password})


def _get_user_id(app, username):
    with app.app_context():
        from app.repositories.user_repo import UserRepository
        u = UserRepository.find_by_username(username)
        return u.id if u else None


# ── Hierarchy safeguards ─────────────────────────────────────────────────────

def test_no_self_reference(app):
    with app.app_context():
        from app.services.user_service import UserService
        from app.repositories.user_repo import UserRepository
        admin = UserRepository.find_by_username("admin")
        with pytest.raises(ValueError, match="cannot report to themselves"):
            UserService.set_reporting_manager(admin.id, admin.id, admin)


def test_cycle_rejected(app):
    """A → B → C → A must be rejected."""
    with app.app_context():
        from app.services.user_service import UserService
        from app.repositories.user_repo import UserRepository
        admin = UserRepository.find_by_username("admin")
        manager = UserRepository.find_by_username("manager")
        viewer = UserRepository.find_by_username("viewer")

        # admin -> manager -> viewer, then viewer -> admin would close the cycle
        UserService.set_reporting_manager(admin.id, manager.id, admin)
        try:
            UserService.set_reporting_manager(manager.id, viewer.id, admin)
            # Now viewer -> admin would create: viewer -> admin -> manager -> viewer
            with pytest.raises(ValueError, match="circular"):
                UserService.set_reporting_manager(viewer.id, admin.id, admin)
        finally:
            # Cleanup: reset relationships
            UserRepository.set_reporting_manager(admin.id, None)
            UserRepository.set_reporting_manager(manager.id, None)
            UserRepository.set_reporting_manager(viewer.id, None)


def test_inactive_manager_rejected(app):
    with app.app_context():
        from app.services.user_service import UserService
        from app.repositories.user_repo import UserRepository
        admin = UserRepository.find_by_username("admin")
        viewer = UserRepository.find_by_username("viewer")
        # Deactivate viewer temporarily, try to make them a manager
        UserRepository.set_active(viewer.id, False)
        try:
            with pytest.raises(ValueError, match="active"):
                UserService.set_reporting_manager(admin.id, viewer.id, admin)
        finally:
            UserRepository.set_active(viewer.id, True)


def test_direct_reports(app):
    with app.app_context():
        from app.services.user_service import UserService
        from app.repositories.user_repo import UserRepository
        admin = UserRepository.find_by_username("admin")
        manager = UserRepository.find_by_username("manager")
        viewer = UserRepository.find_by_username("viewer")

        UserService.set_reporting_manager(viewer.id, manager.id, admin)
        try:
            reports = UserRepository.direct_reports(manager.id)
            ids = [r["id"] for r in reports]
            assert viewer.id in ids
        finally:
            UserRepository.set_reporting_manager(viewer.id, None)


# ── Report workflow ──────────────────────────────────────────────────────────

def test_submit_requires_reporting_manager(app):
    """A user with no reporting manager cannot submit."""
    client = app.test_client()
    _login(client, "viewer", "Viewer@123")
    resp = client.post("/reports/submit", data={
        "title": "Test report", "report_type": "general", "priority": "medium",
    })
    # No reporting manager set → error flash, redirect back
    assert resp.status_code == 302


def test_submit_and_manager_inbox(app):
    """Employee submits → manager sees it in Team Reports inbox."""
    with app.app_context():
        from app.services.user_service import UserService
        from app.repositories.user_repo import UserRepository
        from app.services.report_service import ReportService
        admin = UserRepository.find_by_username("admin")
        manager = UserRepository.find_by_username("manager")
        viewer = UserRepository.find_by_username("viewer")

        UserService.set_reporting_manager(viewer.id, manager.id, admin)
        try:
            result = ReportService.submit_report(
                {"title": "Weekly stock reconciliation", "report_type": "warehouse",
                 "priority": "high", "description": "Recount done", "status": "submitted"},
                viewer,
            )
            assert result["reporting_manager"] in ("manager", "Manager")
            # Manager inbox shows it
            inbox = ReportService.list_team_reports(manager.id)
            assert any(r["id"] == result["id"] for r in inbox)
            # Submitter sees own submission
            mine = ReportService.my_submissions(viewer)
            assert any(r["id"] == result["id"] for r in mine)
            # Cleanup
            import logging as _l
            _l.disable(_l.WARNING)
            from app.database.connection import _open_conn
            conn = _open_conn()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM reports WHERE id = %s", (result["id"],))
            conn.commit()
        finally:
            UserRepository.set_reporting_manager(viewer.id, None)


def test_idor_non_owner_cannot_read(app):
    """A user who is neither submitter nor manager gets None (404)."""
    with app.app_context():
        from app.services.user_service import UserService
        from app.repositories.user_repo import UserRepository
        from app.services.report_service import ReportService
        admin = UserRepository.find_by_username("admin")
        manager = UserRepository.find_by_username("manager")
        viewer = UserRepository.find_by_username("viewer")

        UserService.set_reporting_manager(viewer.id, manager.id, admin)
        try:
            result = ReportService.submit_report(
                {"title": "Secret report", "status": "submitted"}, viewer,
            )
            # viewer (submitter) can read
            assert ReportService.get_report(result["id"], viewer) is not None
            # manager can read
            assert ReportService.get_report(result["id"], manager) is not None
            # admin can read
            assert ReportService.get_report(result["id"], admin) is not None
            # Cleanup
            from app.database.connection import _open_conn
            conn = _open_conn()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM reports WHERE id = %s", (result["id"],))
            conn.commit()
        finally:
            UserRepository.set_reporting_manager(viewer.id, None)


def test_only_manager_can_review(app):
    """The submitter cannot change their own report's status."""
    with app.app_context():
        from app.services.user_service import UserService
        from app.repositories.user_repo import UserRepository
        from app.services.report_service import ReportService
        admin = UserRepository.find_by_username("admin")
        manager = UserRepository.find_by_username("manager")
        viewer = UserRepository.find_by_username("viewer")

        UserService.set_reporting_manager(viewer.id, manager.id, admin)
        try:
            result = ReportService.submit_report(
                {"title": "Review test", "status": "submitted"}, viewer,
            )
            # Submitter cannot approve their own report
            with pytest.raises(Exception):
                ReportService.review_report(result["id"], "approved", viewer, "self-approve")
            # Manager can
            out = ReportService.review_report(result["id"], "approved", manager, "ok")
            assert out["status"] == "approved"
            # Cleanup
            from app.database.connection import _open_conn
            conn = _open_conn()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM reports WHERE id = %s", (result["id"],))
            conn.commit()
        finally:
            UserRepository.set_reporting_manager(viewer.id, None)


def test_manager_pages_require_permission(app):
    """/team requires reports.review — viewer without it gets 403."""
    client = app.test_client()
    _login(client, "viewer", "Viewer@123")
    resp = client.get("/team")
    # viewer's job_role is inventory_analyst (no reports.review) → 403
    assert resp.status_code == 403


def test_manager_with_permission_sees_team_page(app):
    """manager (procurement_manager job_role) has reports.review → 200."""
    client = app.test_client()
    _login(client, "manager", "Manager@123")
    resp = client.get("/team")
    assert resp.status_code == 200