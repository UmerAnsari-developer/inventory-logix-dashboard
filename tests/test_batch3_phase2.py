"""Batch 3 Phase 2 tests: pool metrics + exhaustion alert (GAP-008),
ETL health endpoint (GAP-007), and RBAC on the new endpoints."""
from __future__ import annotations

import psycopg2.pool
import pytest

from app.database import get_cursor
from app.repositories import UserRepository


@pytest.fixture(autouse=True)
def _cleanup_system_alerts(app):
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("DELETE FROM model_monitoring_alerts WHERE sku = 'SYSTEM'")
    yield
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("DELETE FROM model_monitoring_alerts WHERE sku = 'SYSTEM'")


def _session_client(app, username: str):
    """Authenticated client without hitting the /auth/login rate limiter.

    Mirrors the proven pattern from tests/test_frontend_mitigations.py:
    uid is fetched in its own app context; the client is created and used
    OUTSIDE any ambient app context (an outer context breaks the
    strong-session identifier capture).
    """
    from flask_login.utils import _create_identifier

    with app.app_context():
        user = UserRepository.find_by_username(username)
        assert user is not None, f"missing user {username}"
        uid = user.id

    c = app.test_client()
    ident_box: dict = {}

    def _capture():
        ident_box["id"] = _create_identifier()

    app.before_request_funcs.setdefault(None, []).append(_capture)
    try:
        resp = c.get("/static/img/favicon.svg")
        assert resp.status_code == 200
    finally:
        app.before_request_funcs[None].remove(_capture)

    with c.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
        sess["_id"] = ident_box["id"]
    return c


# ── GAP-008: pool stats ─────────────────────────────────────────────────────

def test_get_pool_utilization_shape(app):
    from app.database.connection import get_pool_utilization

    with app.app_context():
        stats = get_pool_utilization()
    assert stats["pool_size"] >= 1
    assert stats["active_connections"] >= 0
    assert 0 <= stats["usage_percent"] <= 100
    assert stats["pools"] >= 1
    assert stats["statement_timeout_ms"] > 0


def test_pool_exhaustion_creates_alert(app, monkeypatch):
    """PoolError on checkout surfaces a SYSTEM/pool_exhaustion alert (GAP-008)."""
    from app.database import connection as conn_mod
    from app.repositories.monitoring_repo import MonitoringRepository

    class _ExhaustedPool:
        def getconn(self):
            raise psycopg2.pool.PoolError("connection pool exhausted")

    with app.app_context():
        monkeypatch.setattr(conn_mod, "_get_pool", lambda params: _ExhaustedPool())
        with app.test_request_context("/"):
            with pytest.raises(psycopg2.pool.PoolError):
                conn_mod.get_connection()
        monkeypatch.undo()  # restore the real pool before DB assertions

        alerts, total = MonitoringRepository.get_alerts(
            sku="SYSTEM", model_name="DB_POOL", alert_type="pool_exhaustion"
        )
        assert total == 1
        assert alerts[0]["severity"] == "critical"
        assert "exhausted" in alerts[0]["message"]


def test_pool_exhaustion_alert_deduplicated(app, monkeypatch):
    from app.database import connection as conn_mod
    from app.repositories.monitoring_repo import MonitoringRepository

    class _ExhaustedPool:
        def getconn(self):
            raise psycopg2.pool.PoolError("connection pool exhausted")

    with app.app_context():
        monkeypatch.setattr(conn_mod, "_get_pool", lambda params: _ExhaustedPool())
        for _ in range(3):
            with app.test_request_context("/"):
                with pytest.raises(psycopg2.pool.PoolError):
                    conn_mod.get_connection()
        monkeypatch.undo()  # restore the real pool before DB assertions

        _, total = MonitoringRepository.get_alerts(
            sku="SYSTEM", model_name="DB_POOL", alert_type="pool_exhaustion"
        )
        assert total == 1, "repeated exhaustion must not accumulate alerts"


# ── GAP-007: ETL health ─────────────────────────────────────────────────────

def test_etl_health_shape(app):
    from app.services import MonitoringService

    with app.app_context():
        health = MonitoringService.etl_health()
    assert health["status"] in ("ok", "never_run", "restore_failed", "error", "unknown")
    assert health["watermark"] >= 0
    assert health["max_movement_id"] >= 0
    assert health["pending_movements"] >= 0


def test_etl_health_reports_pending_backlog(app):
    """Watermark behind max movement id -> pending count reflects the gap."""
    from app.services import MonitoringService

    with app.app_context():
        health = MonitoringService.etl_health()
        expected = max(health["max_movement_id"] - health["watermark"], 0)
        assert health["pending_movements"] == expected


# ── Endpoint RBAC ───────────────────────────────────────────────────────────

def test_pool_status_endpoint_manager_ok_viewer_forbidden(app):
    manager_resp = _session_client(app, "manager").get("/ai/monitoring/pool-status")
    assert manager_resp.status_code == 200
    body = manager_resp.get_json()
    assert body["success"] is True
    assert "usage_percent" in body["data"]

    viewer_resp = _session_client(app, "viewer").get("/ai/monitoring/pool-status")
    assert viewer_resp.status_code == 403


def test_etl_health_endpoint_manager_ok_viewer_forbidden(app):
    manager_resp = _session_client(app, "manager").get("/ai/monitoring/etl-health")
    assert manager_resp.status_code == 200
    body = manager_resp.get_json()
    assert body["success"] is True
    assert "status" in body["data"]

    viewer_resp = _session_client(app, "viewer").get("/ai/monitoring/etl-health")
    assert viewer_resp.status_code == 403