"""Batch 5 Agent B tests: JOB_QUEUE_ENABLED route migration (GAP-012).

Covers ENQUEUE semantics + handler behavior directly — NOT end-to-end
execution (the worker is Agent A's file; TestingConfig never starts it).

Mandatory patterns used here:
- ``queue_enabled`` restoring fixture (the ``app`` fixture is session-scoped —
  config mutation would leak into every later test).
- ``_wait_for_background_threads`` autouse fixture (pattern from
  tests/test_backup_restore_advisory_lock.py:48-71) so daemon threads from
  prior tests never race the next test.
- ``_session_client`` (pattern from tests/test_batch3_phase2.py) — auth
  without hitting the /auth/login rate limiter.
- ETL/restore POSTs stay ≤4 per test; conftest's autouse ``_reset_rate_limiter``
  gives every test fresh memory:// buckets.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import gettempdir
from unittest.mock import patch

import pytest

from app.database import get_cursor
from app.database.connection import _open_conn
from app.repositories import ScheduledAuditReportRepository, UserRepository
from app.services import AuditReportService
from app.utils.cache import monitoring_cache


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def queue_enabled(app):
    """Flag on for this test ONLY — the session-scoped app leaks config."""
    app.config["JOB_QUEUE_ENABLED"] = True
    yield
    app.config["JOB_QUEUE_ENABLED"] = False


@pytest.fixture(autouse=True)
def _wait_for_background_threads():
    """Wait for in-flight ``*_run`` daemon threads from prior tests, wait for
    the ETL route lock to release, then clean stale restore advisory locks
    (pattern from tests/test_backup_restore_advisory_lock.py:48-71)."""
    deadline = time.time() + 5
    while time.time() < deadline:
        alive = [th for th in threading.enumerate() if th.name.endswith("_run") and th.is_alive()]
        if not alive:
            break
        time.sleep(0.2)

    from app.routes.ui import _ETL_RUN_LOCK

    deadline = time.time() + 10
    while time.time() < deadline and _ETL_RUN_LOCK.locked():
        time.sleep(0.2)

    try:
        conn = _open_conn()
        try:
            from app.services.backup_service import _cleanup_stale_restore_lock
            _cleanup_stale_restore_lock(conn)
        finally:
            conn.close()
    except Exception:
        pass  # best-effort cleanup


@pytest.fixture(autouse=True)
def _cleanup_test_rows(app):
    """Delete only rows this test created.

    job_queue: diff-based (fixed task names can't carry uuid suffixes) —
    snapshot ids before, delete new ids after, scoped to the three task
    names these tests touch. etl_warehouse_state: fixed key list.
    """
    with app.app_context():
        with get_cursor() as cur:
            cur.execute(
                "SELECT id FROM job_queue WHERE task_name IN "
                "('run_etl', 'restore_backup', 'generate_report')"
            )
            before = {r["id"] for r in cur.fetchall()}
    yield
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "SELECT id FROM job_queue WHERE task_name IN "
                "('run_etl', 'restore_backup', 'generate_report')"
            )
            for r in cur.fetchall():
                if r["id"] not in before:
                    cur.execute("DELETE FROM job_queue WHERE id = %s", (r["id"],))
            cur.execute(
                "DELETE FROM etl_warehouse_state WHERE state_key IN "
                "('etl_job_status', 'etl_job_error', 'warehouse_etl_ok', "
                "'restore_job_status', 'restore_job_error')"
            )


@pytest.fixture
def admin_user_id(app):
    with app.app_context():
        admin = UserRepository.find_by_username("admin")
        assert admin is not None, "admin user must exist"
        return admin.id


@pytest.fixture
def seeded_backup(app, admin_user_id):
    """system_backups row pointing at a REAL file. checksum NULL skips the
    verify step; encrypted FALSE skips decryption in the pre-check."""
    tmp = Path(gettempdir()) / f"test_b5_backup_{uuid.uuid4().hex[:8]}.dump"
    tmp.write_bytes(b"fake backup payload")
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO system_backups (backup_name, backup_type, file_path, size, status, created_by, encrypted)
                VALUES (%s, 'full', %s, %s, 'success', %s, FALSE)
                RETURNING id
                """,
                (f"test_b5_{uuid.uuid4().hex[:8]}", str(tmp), tmp.stat().st_size, admin_user_id),
            )
            backup_id = cur.fetchone()["id"]
    yield backup_id
    try:
        tmp.unlink(missing_ok=True)
    except Exception:
        pass
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("DELETE FROM system_backups WHERE id = %s", (backup_id,))


@pytest.fixture
def seeded_report(app, admin_user_id):
    with app.app_context():
        report_id = ScheduledAuditReportRepository.create(
            name=f"test_b5_report_{uuid.uuid4().hex[:8]}",
            description="batch5 job-queue route test",
            format="CSV",
            frequency="daily",
            parameters={},
            next_run_time=(datetime.now() + timedelta(days=1)).isoformat(),
            created_by=admin_user_id,
        )
    yield report_id
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("DELETE FROM scheduled_audit_reports WHERE id = %s", (report_id,))


def _session_client(app, username: str):
    """Authenticated client without hitting the /auth/login rate limiter
    (pattern from tests/test_batch3_phase2.py)."""
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


def _set_etl_state(app, key: str, value: str) -> None:
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO etl_warehouse_state (state_key, value, updated_at) "
                "VALUES (%s, %s, NOW()) ON CONFLICT (state_key) "
                "DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
                (key, value),
            )


def _count_jobs(app, task_name: str) -> int:
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM job_queue WHERE task_name = %s", (task_name,))
            return cur.fetchone()["c"]


def _wait_for_restore_run_thread(timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        alive = [th for th in threading.enumerate() if th.name == "restore_run" and th.is_alive()]
        if not alive:
            return
        time.sleep(0.1)


# ── B1: monitoring_run_etl flag branch ───────────────────────────────────────

def test_run_etl_flag_on_enqueues_job(app, queue_enabled):
    client = _session_client(app, "admin")
    resp = client.post("/monitoring/run-etl", follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT * FROM job_queue WHERE task_name = 'run_etl'")
            rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert rows[0]["payload"]["force"] is True
    assert "ETL queued (job #" in resp.get_data(as_text=True)


def test_run_etl_flag_on_rejects_duplicate_enqueue(app, queue_enabled):
    client = _session_client(app, "admin")
    assert client.post("/monitoring/run-etl").status_code == 302
    assert client.post("/monitoring/run-etl").status_code == 302
    assert _count_jobs(app, "run_etl") == 1
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    assert any("already queued or running" in m for _, m in flashes)
    assert any(cat == "warning" for cat, _ in flashes)


def test_run_etl_flag_off_spawns_thread_no_enqueue(app):
    client = _session_client(app, "admin")
    from app.routes.ui import _ETL_RUN_LOCK

    # Patch etl_database so the spawned daemon thread finishes instantly
    # instead of running a real warehouse rebuild; keep the patch active
    # until the thread is done (it resolves the import at call time).
    with patch("app.database.connection.etl_database") as mock_etl:
        mock_etl.return_value = {"warehouse_etl_ok": True}
        resp = client.post("/monitoring/run-etl")
        assert resp.status_code == 302
        deadline = time.time() + 10
        while time.time() < deadline and _ETL_RUN_LOCK.locked():
            time.sleep(0.1)
    assert not _ETL_RUN_LOCK.locked()
    assert _count_jobs(app, "run_etl") == 0


# ── B2: F4 interrupted read-check ────────────────────────────────────────────

def test_f4_interrupted_not_shown_while_queue_job_running(app, queue_enabled):
    _set_etl_state(app, "etl_job_status", "running")
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO job_queue (task_name, payload, status, started_at) "
                "VALUES ('run_etl', '{}', 'running', NOW())"
            )
    monitoring_cache.invalidate("")
    client = _session_client(app, "admin")
    resp = client.get("/monitoring")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "interrupted" not in body
    assert "running" in body


def test_f4_interrupted_still_shown_when_no_queue_job(app, queue_enabled):
    _set_etl_state(app, "etl_job_status", "running")
    monitoring_cache.invalidate("")
    client = _session_client(app, "admin")
    resp = client.get("/monitoring")
    assert resp.status_code == 200
    assert "interrupted" in resp.get_data(as_text=True)


# ── B3/B4/B5: restore flag branch + synchronous handler ─────────────────────

def test_restore_flag_on_enqueues_after_prechecks(app, queue_enabled, seeded_backup, admin_user_id):
    client = _session_client(app, "admin")
    resp = client.post(f"/admin/backup/restore/{seeded_backup}")
    assert resp.status_code == 302
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT * FROM job_queue WHERE task_name = 'restore_backup'")
            rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert rows[0]["payload"]["backup_id"] == seeded_backup
    assert rows[0]["payload"]["user_id"] == admin_user_id


def test_restore_flag_on_precheck_failure_does_not_enqueue(app, queue_enabled):
    client = _session_client(app, "admin")
    resp = client.post("/admin/backup/restore/999999")
    assert resp.status_code == 302
    assert _count_jobs(app, "restore_backup") == 0
    with client.session_transaction() as sess:
        messages = [m for _, m in sess.get("_flashes", [])]
    assert any("not found" in m.lower() for m in messages)


def test_restore_flag_off_thread_path_no_enqueue(app, seeded_backup):
    client = _session_client(app, "admin")
    resp = client.post(f"/admin/backup/restore/{seeded_backup}")
    assert resp.status_code == 302
    # The thread fails fast (no encryption_key_id → failed keys, no pg_restore).
    _wait_for_restore_run_thread()
    assert _count_jobs(app, "restore_backup") == 0


def test_restore_handler_is_synchronous_no_thread_spawn(app, admin_user_id):
    from app.services import backup_service

    before = {th.name for th in threading.enumerate() if th.is_alive()}
    with app.app_context():
        result = backup_service._restore_backup_handler(
            {"backup_id": 999999, "user_id": admin_user_id}
        )
    new_threads = [
        th.name
        for th in threading.enumerate()
        if th.is_alive() and th.name not in before
    ]
    assert isinstance(result, dict)
    assert result["success"] is False
    assert not any(name.endswith("_run") or "restore" in name.lower() for name in new_threads)


def test_restore_handler_writes_monitoring_keys(app, admin_user_id):
    from app.services import backup_service

    with app.app_context():
        result = backup_service._restore_backup_handler(
            {"backup_id": 999999, "user_id": admin_user_id}
        )
        assert result["success"] is False
        with get_cursor() as cur:
            cur.execute(
                "SELECT value FROM etl_warehouse_state WHERE state_key = 'restore_job_status'"
            )
            row = cur.fetchone()
    assert row is not None
    assert row["value"] == "failed"


# ── B6: generate_report_async flag branch ────────────────────────────────────

def test_generate_report_async_flag_on_returns_queue_id(app, queue_enabled, seeded_report, admin_user_id):
    with app.app_context():
        job_id = AuditReportService.generate_report_async(seeded_report, admin_user_id)
        assert job_id.isdigit()
        with get_cursor() as cur:
            cur.execute("SELECT * FROM job_queue WHERE id = %s", (int(job_id),))
            row = cur.fetchone()
    assert row is not None
    assert row["task_name"] == "generate_report"
    assert row["payload"]["user_id"] == admin_user_id
    assert row["payload"]["report_id"] == seeded_report


def test_generate_report_handler_reads_user_id_key(app, queue_enabled, seeded_report, admin_user_id):
    """H1 regression: the handler must read payload['user_id'] (the key the
    flag-on enqueue writes) — the old 'generated_by' key silently dropped the
    completion notification."""
    from app.services.audit_report_service import _generate_report_handler

    with app.app_context():
        result = _generate_report_handler({
            "report_id": seeded_report,
            "user_id": admin_user_id,
        })
        assert result["success"] is True
        with get_cursor() as cur:
            cur.execute(
                "SELECT user_id FROM notifications WHERE title LIKE %s "
                "ORDER BY created_at DESC LIMIT 1",
                ("Audit Report Generated%",),
            )
            row = cur.fetchone()
    assert row is not None, "completion notification must be created"
    assert row["user_id"] == admin_user_id


def test_generate_report_async_flag_off_returns_uuid(app, admin_user_id):
    from app.services.job_tracker import JobTracker

    with app.app_context():
        # Nonexistent report id → the daemon thread fails fast in memory
        # (no report rows written, no notification created).
        job_id = AuditReportService.generate_report_async(999999, admin_user_id)
        assert "-" in job_id
        assert len(job_id) == 36
        JobTracker.cleanup_job(job_id)


# ── B7: job_status adapter ───────────────────────────────────────────────────

_CONTRACT_KEYS = (
    "job_id", "job_type", "user_id", "status", "progress", "current_step",
    "total_steps", "message", "result", "error", "metadata",
    "created_at", "updated_at", "started_at", "completed_at",
)


def test_job_status_queue_job_shape_matches_tracker_contract(app, admin_user_id):
    from app.services.job_queue_service import JobQueueService

    with app.app_context():
        job_id = JobQueueService.enqueue(
            "generate_report", {"report_id": 4242, "user_id": admin_user_id}
        )
    client = _session_client(app, "admin")
    resp = client.get(f"/admin/audit_reports/job_status/{job_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    for key in _CONTRACT_KEYS:
        assert key in data, f"missing contract key: {key}"
    assert data["job_id"] == str(job_id)
    assert data["job_type"] == "audit_report"
    assert data["user_id"] == admin_user_id
    assert data["status"] == "pending"
    assert data["progress"] == 0
    assert data["current_step"] == 0
    assert data["total_steps"] == 4
    assert data["message"] == "Queued"
    assert data["metadata"] == {"report_id": 4242}
    assert data["result"] is None
    assert data["error"] is None
    assert data["started_at"] is None
    assert data["completed_at"] is None


def test_job_status_dead_maps_to_failed(app, admin_user_id):
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO job_queue (task_name, payload, status, error, completed_at)
                VALUES ('generate_report', %s, 'dead', 'boom', NOW())
                RETURNING id
                """,
                (json.dumps({"report_id": 4242, "user_id": admin_user_id}),),
            )
            job_id = cur.fetchone()["id"]
    client = _session_client(app, "admin")
    resp = client.get(f"/admin/audit_reports/job_status/{job_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "failed"
    assert data["message"] == "boom"
    assert data["progress"] == 100
    assert data["current_step"] == 4


def test_job_status_forbidden_for_other_user(app, admin_user_id):
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO job_queue (task_name, payload, status)
                VALUES ('generate_report', %s, 'pending')
                RETURNING id
                """,
                (json.dumps({"report_id": 4242, "user_id": admin_user_id}),),
            )
            job_id = cur.fetchone()["id"]
    # manager passes @write_roles_required but does not own the job → 403
    client = _session_client(app, "manager")
    resp = client.get(f"/admin/audit_reports/job_status/{job_id}")
    assert resp.status_code == 403


def test_job_status_legacy_uuid_still_resolved(app, queue_enabled, admin_user_id):
    from app.services.job_tracker import JobTracker

    with app.app_context():
        uuid_id = JobTracker.create_job(
            job_type="audit_report",
            user_id=admin_user_id,
            total_steps=4,
            metadata={"report_id": 4242},
        )
    try:
        client = _session_client(app, "admin")
        resp = client.get(f"/admin/audit_reports/job_status/{uuid_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["job_id"] == uuid_id
        assert data["status"] == "pending"
    finally:
        JobTracker.cleanup_job(uuid_id)
