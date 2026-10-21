"""Batch 3 Phase 2 tests: pool metrics + exhaustion alert (GAP-008)."""
from __future__ import annotations

import psycopg2.pool
import pytest

from app.database import get_cursor


@pytest.fixture(autouse=True)
def _cleanup_system_alerts(app):
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("DELETE FROM model_monitoring_alerts WHERE sku = 'SYSTEM'")
    yield
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("DELETE FROM model_monitoring_alerts WHERE sku = 'SYSTEM'")


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
