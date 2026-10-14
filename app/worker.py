"""Poll-based job-queue worker (GAP-012 Batch 5).

Executes ``job_queue`` rows that nothing executed before: every tick it
requeues stale ``running`` rows (crash self-heal), atomically claims due
``pending`` rows (``FOR UPDATE SKIP LOCKED`` in one transaction), and runs
each through ``JobQueueService._execute_job``.

Started in-process by ``create_app`` behind ``JOB_QUEUE_ENABLED``, or
standalone via ``python -m app.worker``.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time

from .database import get_cursor
from .services.job_queue_service import Job, JobQueueService

POLL_SECONDS = 5
STALE_MINUTES = 10
BATCH_SIZE = 10

LOGGER = logging.getLogger(__name__)


def _worker_id() -> str:
    # socket.gethostname — os has no gethostname (spec typo).
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}"


def requeue_stale() -> int:
    """Requeue (or dead) ``running`` rows older than STALE_MINUTES.

    One atomic statement: SET expressions see the OLD ``attempts`` value, so
    ``attempts + 1 >= max_attempts`` mirrors ``_execute_job``'s backoff
    semantics. A killed worker's stranded rows self-heal here on the next
    tick; at max attempts the job dies with a stale error (poison stop).
    """
    with get_cursor(commit=True) as cur:
        cur.execute(
            f"""
            UPDATE job_queue
            SET status       = CASE WHEN attempts + 1 >= max_attempts
                                    THEN 'dead' ELSE 'pending' END,
                attempts     = attempts + 1,
                next_run     = now(),
                locked_by    = NULL,
                locked_at    = NULL,
                error        = CASE WHEN attempts + 1 >= max_attempts
                                    THEN 'stale: running exceeded {STALE_MINUTES} minutes'
                                    ELSE error END,
                completed_at = CASE WHEN attempts + 1 >= max_attempts
                                    THEN now() ELSE completed_at END
            WHERE status = 'running'
              AND started_at < now() - interval '{STALE_MINUTES} minutes'
            """
        )
        return cur.rowcount


def claim_jobs(batch_size: int = BATCH_SIZE) -> list[Job]:
    """Atomically claim up to ``batch_size`` due pending jobs for this worker.

    One transaction: ``SELECT ... FOR UPDATE SKIP LOCKED`` locks the rows,
    the UPDATE marks them running with this worker's id, COMMIT releases the
    locks — two concurrent claimers can never take the same row. ``SELECT *``
    (not the ``job_queue_get_status`` proc, which omits payload/priority/
    next_run) so ``Job(**row)`` gets all 15 columns. This claim finally
    writes ``locked_at``.
    """
    with get_cursor(commit=True) as cur:
        cur.execute(
            "SELECT * FROM job_queue WHERE status='pending' AND next_run <= now() "
            "ORDER BY priority DESC, created_at LIMIT %s FOR UPDATE SKIP LOCKED",
            (batch_size,),
        )
        rows = cur.fetchall()
        if rows:
            cur.execute(
                "UPDATE job_queue SET status='running', locked_by=%s, locked_at=now(), "
                "started_at=now() WHERE id = ANY(%s)",
                (_worker_id(), [r["id"] for r in rows]),
            )
    return [Job(**row) for row in rows]


def tick(batch_size: int = BATCH_SIZE) -> int:
    """One poll cycle: stale-requeue, claim, execute. Returns executed count."""
    requeue_stale()
    jobs = claim_jobs(batch_size)
    for job in jobs:
        try:
            # The guarded pending→running UPDATE inside _execute_job no-ops
            # (claim already set running) — the handler still runs.
            JobQueueService._execute_job(job)
        except Exception:
            # One bad job must never kill the loop.
            LOGGER.exception("Worker tick: job %s (%s) crashed", job.id, job.task_name)
    return len(jobs)


def run_forever(app, stop_event: threading.Event | None = None,
                poll_seconds: int = POLL_SECONDS) -> None:
    """Poll loop; exits when ``stop_event`` is set (or runs forever)."""
    LOGGER.info("Job-queue worker polling every %ss", poll_seconds)
    while True:
        try:
            with app.app_context():
                tick()
        except Exception:
            LOGGER.exception("Job-queue worker tick failed")
        if stop_event:
            if stop_event.wait(poll_seconds):
                break
        else:
            time.sleep(poll_seconds)
    LOGGER.info("Job-queue worker stopped")


def start_worker_thread(app) -> tuple[threading.Thread, threading.Event]:
    """Start the worker as a daemon thread. Returns (thread, stop_event).

    The stop_event is required so tests (and future callers) can shut the
    poller down deterministically instead of leaking a 5s-polling thread.
    """
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_forever,
        args=(app,),
        kwargs={"stop_event": stop_event},
        name="job-queue-worker",
        daemon=True,
    )
    thread.start()
    return thread, stop_event


if __name__ == "__main__":
    # Accepted quirk: in production (DEBUG=False) create_app() below ALSO
    # starts the in-process worker thread, so standalone mode runs two
    # pollers in one process — safe by construction because claim_jobs uses
    # FOR UPDATE SKIP LOCKED (two claimers can never take the same row).
    # Under the dev reloader the reloader-parent guard suppresses the thread.
    from . import create_app

    app = create_app()
    LOGGER.info("Standalone job-queue worker started")
    run_forever(app)
