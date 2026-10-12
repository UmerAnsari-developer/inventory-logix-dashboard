"""Batch 3 Phase 3 tests: audit hash-chain tamper evidence (GAP-011),
retention handler, and alert routing (GAP-009)."""
from __future__ import annotations

import uuid

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
    """Authenticated client (proven pattern — client used OUTSIDE app_context)."""
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
        assert c.get("/static/img/favicon.svg").status_code == 200
    finally:
        app.before_request_funcs[None].remove(_capture)

    with c.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
        sess["_id"] = ident_box["id"]
    return c


def _insert_audit_row(app, action: str) -> int:
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO audit_log (user_id, action, target_type, detail, ip_address)
                VALUES (NULL, %s, 'test', '{"t": 1}'::jsonb, '127.0.0.1')
                RETURNING id
                """,
                (action,),
            )
            return cur.fetchone()["id"]


# ── GAP-011: hash chain ─────────────────────────────────────────────────────

def test_new_audit_rows_are_chained(app):
    """Every new audit row carries prev_hash/row_hash and links to its predecessor."""
    id1 = _insert_audit_row(app, f"chain_test_a_{uuid.uuid4().hex[:6]}")
    id2 = _insert_audit_row(app, f"chain_test_b_{uuid.uuid4().hex[:6]}")

    with app.app_context():
        with get_cursor() as cur:
            cur.execute(
                "SELECT id, prev_hash, row_hash FROM audit_log WHERE id = ANY(%s) ORDER BY id",
                ([id1, id2],),
            )
            rows = cur.fetchall()

    assert rows[0]["row_hash"], "row_hash must be computed by the trigger"
    assert rows[1]["prev_hash"] == rows[0]["row_hash"], "chain must link rows"
    assert rows[1]["row_hash"] != rows[0]["row_hash"]


def test_verify_integrity_reports_intact_chain(app):
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_audit_verify_integrity(%s)", (2000,))
            row = cur.fetchone()
    assert row["rows_checked"] > 0
    assert row["broken_links"] == 0, "chain must be intact on an untampered log"
    assert row["bad_hashes"] == 0


def test_verify_integrity_detects_tampering(app):
    """Modifying a row's action without recomputing its hash must be flagged."""
    token = uuid.uuid4().hex[:8]
    id1 = _insert_audit_row(app, f"tamper_a_{token}")
    id2 = _insert_audit_row(app, f"tamper_b_{token}")

    with app.app_context():
        try:
            with get_cursor(commit=True) as cur:
                cur.execute(
                    "UPDATE audit_log SET action = 'TAMPERED' WHERE id = %s", (id1,)
                )
            with get_cursor() as cur:
                cur.execute("SELECT * FROM sp_audit_verify_integrity(%s)", (2000,))
                row = cur.fetchone()
            assert row["bad_hashes"] >= 1, "tampered row must fail hash recompute"
            assert row["first_broken_id"] is not None
        finally:
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM audit_log WHERE id = ANY(%s)", ([id1, id2],))


def test_verify_integrity_endpoint_rbac(app):
    manager_resp = _session_client(app, "manager").get(
        "/admin/audit_reports/verify-integrity?limit=500"
    )
    assert manager_resp.status_code == 200
    body = manager_resp.get_json()
    assert body["success"] is True
    assert "intact" in body

    viewer_resp = _session_client(app, "viewer").get(
        "/admin/audit_reports/verify-integrity"
    )
    assert viewer_resp.status_code == 403


# ── GAP-011: retention handler ──────────────────────────────────────────────

def test_run_retention_returns_results(app):
    from app.services.monitoring_service import run_retention

    with app.app_context():
        result = run_retention()
    assert result["success"] is True
    objects = {r["object"] for r in result["results"]}
    assert {"audit_log", "user_sessions", "idempotency_keys", "rate_limit_state"} <= objects


# ── GAP-009: alert routing ──────────────────────────────────────────────────

def test_notify_alert_db_only_when_unconfigured(app, monkeypatch):
    """No channels configured -> all skipped, no crash, no HTTP calls."""
    from app.services import alert_notifier

    with app.app_context():
        monkeypatch.setattr(alert_notifier, "_send_email", lambda a: "skipped")
        results = alert_notifier.notify_alert({
            "alert_type": "etl_failure", "severity": "critical",
            "message": "m", "recommended_action": "a",
        })
    assert results["slack"] == "skipped"
    assert results["webhook"] == "skipped"


def test_notify_alert_webhook_delivery(app, monkeypatch):
    from app.services import alert_notifier

    posted = {}

    class _Resp:
        status_code = 200

    def fake_post(url, json=None, timeout=None):
        posted["url"] = url
        posted["json"] = json
        return _Resp()

    with app.app_context():
        app.config["ALERT_WEBHOOK_URL"] = "https://hooks.example.test/x"
        try:
            monkeypatch.setattr(alert_notifier.requests, "post", fake_post)
            results = alert_notifier.notify_alert({
                "alert_type": "backup_failure", "severity": "critical",
                "message": "backup failed", "recommended_action": "act",
            })
        finally:
            app.config["ALERT_WEBHOOK_URL"] = ""

    assert results["webhook"] == "sent"
    assert posted["url"] == "https://hooks.example.test/x"
    assert posted["json"]["alert_type"] == "backup_failure"


def test_notify_alert_webhook_failure_never_raises(app, monkeypatch):
    from app.services import alert_notifier

    def boom(url, json=None, timeout=None):
        raise alert_notifier.requests.ConnectionError("down")

    with app.app_context():
        app.config["ALERT_WEBHOOK_URL"] = "https://hooks.example.test/x"
        try:
            monkeypatch.setattr(alert_notifier.requests, "post", boom)
            results = alert_notifier.notify_alert({
                "alert_type": "etl_failure", "severity": "critical",
                "message": "m", "recommended_action": "a",
            })
        finally:
            app.config["ALERT_WEBHOOK_URL"] = ""

    assert results["webhook"] == "failed"  # logged, not raised


def test_system_alert_triggers_routing(app, monkeypatch):
    """_maybe_create_system_alert routes after persisting (GAP-009 wiring)."""
    from app.services import monitoring_service

    routed = {}

    def fake_notify(alert):
        routed["type"] = alert["alert_type"]
        return {"email": "skipped", "slack": "skipped", "webhook": "skipped"}

    with app.app_context():
        # _maybe_create_system_alert lazily imports notify_alert at call time,
        # so patching the source module attribute is sufficient.
        monkeypatch.setattr("app.services.alert_notifier.notify_alert", fake_notify)
        monitoring_service._maybe_create_system_alert({
            "sku": "SYSTEM", "model_name": "ROUTING_TEST",
            "alert_date": "2026-10-12", "alert_type": "routing_probe",
            "severity": "critical", "metric": "probe",
            "baseline_value": None, "current_value": None,
            "change_percent": 0.0, "message": "probe",
            "recommended_action": "none", "status": "new",
        })

    assert routed.get("type") == "routing_probe"