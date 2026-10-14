"""Job-queue worker tests (GAP-012 Batch 5, Agent A).

Direct-tick pattern: every test drives tick()/claim_jobs()/requeue_stale()
inside an app context — deterministic, no polling, no threads (except the
one thread-lifecycle test, which stops its worker before returning).

Each test enqueues under a UNIQUE task name (``test_task_<hex8>``) so
``register_handler``'s duplicate-ValueError can never fire and no handler
cleanup is needed. Teardown deletes only rows those names created — never
other rows in the shared dev DB.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.database import get_cursor
from app.services.job_queue_service import JobQueueService
from app.worker import claim_jobs, requeue_stale, start_worker_thread, tick


@pytest.fixture(autouse=True)
def _ctx(app):
    """Every DB call in this module (helpers included) runs in app context."""
    with app.app_context():
        yield


@pytest.fixture(autouse=True)
def _cleanup_test_jobs(_ctx):
    yield
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM job_queue WHERE task_name LIKE 'test_task_%'")


def _unique_task() -> str:
    return f"test_task_{uuid4().hex[:8]}"


def _fetch(job_id: int) -> dict:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM job_queue WHERE id = %s", (job_id,))
        return cur.fetchone()


def _make_running(job_id: int, *, started_ago_minutes: int, attempts: int = 0,
                  locked: bool = False) -> None:
    """Force a row into the running state with a backdated started_at."""
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE job_queue SET status='running', "
            "started_at = now() - (%s * interval '1 minute'), attempts = %s, "
            "locked_by = CASE WHEN %s THEN 'test-worker' ELSE locked_by END, "
            "locked_at = CASE WHEN %s THEN now() ELSE locked_at END "
            "WHERE id = %s",
            (started_ago_minutes, attempts, locked, locked, job_id),
        )


# --- requeue_stale ---------------------------------------------------------

def test_requeue_stale_requeues_old_running(app):
    task = _unique_task()
    job_id = JobQueueService.enqueue(task, {})
    _make_running(job_id, started_ago_minutes=11, attempts=0)

    requeue_stale()

    row = _fetch(job_id)
    assert row["status"] == "pending"
    assert row["attempts"] == 1


def test_requeue_stale_deads_at_max_attempts(app):
    task = _unique_task()
    job_id = JobQueueService.enqueue(task, {}, max_attempts=3)
    _make_running(job_id, started_ago_minutes=11, attempts=2)  # max_attempts - 1

    requeue_stale()

    row = _fetch(job_id)
    assert row["status"] == "dead"
    assert "stale" in (row["error"] or "")
    assert row["completed_at"] is not None


def test_requeue_stale_ignores_fresh_running(app):
    task = _unique_task()
    job_id = JobQueueService.enqueue(task, {})
    _make_running(job_id, started_ago_minutes=0, attempts=1)

    requeue_stale()

    row = _fetch(job_id)
    assert row["status"] == "running"
    assert row["attempts"] == 1  # untouched


def test_requeue_stale_clears_lock_columns(app):
    task = _unique_task()
    job_id = JobQueueService.enqueue(task, {})
    _make_running(job_id, started_ago_minutes=11, locked=True)

    requeue_stale()

    row = _fetch(job_id)
    assert row["locked_by"] is None
    assert row["locked_at"] is None


# --- claim_jobs ------------------------------------------------------------

def test_claim_marks_running_with_worker_and_locked_at(app):
    task = _unique_task()
    job_id = JobQueueService.enqueue(task, {})

    claimed = claim_jobs()

    assert job_id in [j.id for j in claimed]
    row = _fetch(job_id)
    assert row["status"] == "running"
    assert row["locked_by"]  # non-null worker id
    assert row["locked_at"] is not None


def test_claim_second_call_returns_empty(app):
    task = _unique_task()
    job_id = JobQueueService.enqueue(task, {})

    first = claim_jobs()
    second = claim_jobs()

    assert job_id in [j.id for j in first]
    # A claimed (running) job can never be claimed twice.
    assert job_id not in [j.id for j in second]
    assert [j for j in second if j.task_name == task] == []


def test_claim_respects_priority_order(app):
    task = _unique_task()
    low = JobQueueService.enqueue(task, {}, priority=0)
    high = JobQueueService.enqueue(task, {}, priority=5)

    claimed = claim_jobs(10)

    ids = [j.id for j in claimed]
    assert low in ids and high in ids
    assert ids.index(high) < ids.index(low)


# --- tick ------------------------------------------------------------------

def test_tick_completes_job_with_result(app):
    task = _unique_task()
    job_id = JobQueueService.enqueue(task, {})
    JobQueueService.register_handler(
        task, lambda payload: {"ok": True, "echo": payload}
    )

    executed = tick()

    assert executed >= 1
    row = _fetch(job_id)
    assert row["status"] == "completed"
    assert row["result"] == {"ok": True, "echo": {}}


def test_tick_requeues_failed_job_with_backoff(app):
    task = _unique_task()
    job_id = JobQueueService.enqueue(task, {}, max_attempts=3)

    def _boom(payload):
        raise RuntimeError("boom")

    JobQueueService.register_handler(task, _boom)

    tick()

    row = _fetch(job_id)
    assert row["status"] == "pending"
    assert row["attempts"] == 1
    assert row["next_run"] > datetime.now(timezone.utc)


def test_tick_deads_job_at_max_attempts(app):
    task = _unique_task()
    job_id = JobQueueService.enqueue(task, {}, max_attempts=1)

    def _boom(payload):
        raise RuntimeError("boom")

    JobQueueService.register_handler(task, _boom)

    tick()

    row = _fetch(job_id)
    assert row["status"] == "dead"
    # _safe_error keeps the plain message, strips nothing here — but it is a
    # single sanitized line, never a stack trace.
    assert row["error"] == "boom"


def test_tick_survives_handlerless_job(app):
    task = _unique_task()
    job_id = JobQueueService.enqueue(task, {})  # NO handler registered

    tick()  # must not raise — _execute_job's ValueError is caught per-job

    row = _fetch(job_id)
    assert row["status"] == "running"  # claimed, then stuck by the missing handler

    # Backdate so the NEXT tick's stale-requeue recovers it.
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE job_queue SET started_at = now() - interval '11 minutes' "
            "WHERE id = %s",
            (job_id,),
        )

    tick()

    row = _fetch(job_id)
    # requeue_stale requeued it (attempts 0→1); the same tick immediately
    # re-claimed it (still no handler) → running again, attempts preserved.
    assert row["attempts"] == 1
    assert row["status"] == "running"


# --- thread lifecycle ------------------------------------------------------

def test_start_worker_thread_and_stop(app, monkeypatch):
    # Patch tick to a no-op: this test asserts thread LIFECYCLE (name, daemon,
    # clean stop) — a live poller against the shared dev DB could claim and
    # execute stray real pending rows (M2).
    monkeypatch.setattr("app.worker.tick", lambda *a, **k: 0)
    thread, stop_event = start_worker_thread(app)
    try:
        assert thread.name == "job-queue-worker"
        assert thread.daemon
        assert thread.is_alive()
    finally:
        stop_event.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
