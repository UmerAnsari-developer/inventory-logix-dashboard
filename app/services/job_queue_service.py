"""Persistent job queue using PostgreSQL + pg_cron (GAP-012).

Replaces in-memory JobTracker with a durable, multi-worker-safe queue.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from ..database import get_cursor
from ..database.etl import _safe_error

LOGGER = logging.getLogger(__name__)


@dataclass
class Job:
    # Columns returned by job_queue_get_status() (positional-safe order:
    # fields WITHOUT defaults first, defaulted fields last — Job(**row)
    # is keyword construction so order only matters for defaults).
    id: int
    task_name: str
    status: str
    attempts: int
    max_attempts: int
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error: Optional[str]
    result: Optional[dict]
    # Columns NOT returned by job_queue_get_status() — defaulted so
    # Job(**row) never raises TypeError.
    payload: dict = field(default_factory=dict)
    priority: int = 0
    next_run: Optional[datetime] = None
    locked_by: Optional[str] = None
    locked_at: Optional[datetime] = None


class JobQueueService:
    """Thread-safe job queue with PostgreSQL backend + pg_cron scheduling."""

    _handlers: dict[str, Callable[[dict], Any]] = {}

    @classmethod
    def register_handler(cls, task_name: str, handler: Callable[[dict], Any]) -> None:
        """Register a task handler. Called at module load time."""
        if task_name in cls._handlers:
            raise ValueError(f"Handler for '{task_name}' already registered")
        cls._handlers[task_name] = handler

    @classmethod
    def enqueue(
        cls,
        task_name: str,
        payload: dict,
        *,
        priority: int = 0,
        max_attempts: int = 3,
        delay_seconds: int = 0,
    ) -> int:
        """Add a job to the queue. Returns job_id."""
        with get_cursor(commit=True) as cur:
            # SELECT id FROM <set-returning fn> — the fn-in-target-list form
            # returns the composite as one column named after the function,
            # which breaks the ["id"] lookup.
            cur.execute(
                "SELECT id FROM job_queue_enqueue(%s, %s, %s, %s, %s)",
                (task_name, json.dumps(payload), priority, max_attempts, delay_seconds),
            )
            return cur.fetchone()["id"]

    @classmethod
    def get_status(cls, job_id: int) -> Optional[Job]:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM job_queue_get_status(%s)", (job_id,))
            row = cur.fetchone()
            return Job(**row) if row else None

    @classmethod
    def _execute_job(cls, job: Job) -> None:
        """Execute a single job with retry logic."""
        handler = cls._handlers.get(job.task_name)
        if not handler:
            raise ValueError(f"No handler for task: {job.task_name}")

        # Mark running (guarded: only a pending job may transition)
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE job_queue SET status='running', started_at=now() "
                "WHERE id=%s AND status='pending'",
                (job.id,),
            )

        try:
            result = handler(job.payload)
            with get_cursor(commit=True) as cur:
                cur.execute(
                    """
                    UPDATE job_queue SET status='completed', completed_at=now(), result=%s
                    WHERE id=%s
                    """,
                    (json.dumps(result), job.id),
                )
        except Exception as e:
            # _safe_error strips DB internals (host/port/constraint SQL) —
            # the error column is readable via job_queue_get_status.
            safe = _safe_error(e)
            LOGGER.exception("Job %s failed: %s", job.id, safe)
            with get_cursor(commit=True) as cur:
                if job.attempts + 1 >= job.max_attempts:
                    cur.execute(
                        """
                        UPDATE job_queue SET status='dead', completed_at=now(), error=%s
                        WHERE id=%s
                        """,
                        (safe, job.id),
                    )
                else:
                    # SET expressions see the OLD attempts value — use
                    # attempts+1 so the first retry actually backs off.
                    cur.execute(
                        """
                        UPDATE job_queue SET status='pending', attempts=attempts+1,
                               next_run=now() + make_interval(mins => attempts + 1)
                        WHERE id=%s
                        """,
                        (job.id,),
                    )

    @classmethod
    def process_batch(cls, batch_size: int = 100) -> int:
        """Process pending jobs. Called by external worker listening on pg_notify.

        Returns number of jobs dispatched.
        """
        dispatched = 0
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT job_queue_process_batch(%s) AS dispatched", (batch_size,))
            row = cur.fetchone()
            if row:
                dispatched = row["dispatched"] or 0
        return dispatched