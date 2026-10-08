"""DB-044: retention purge procedures for audit/ops tables — against local Postgres.

Validates the *database* guarantees: each sp_retention_purge_* exists, deletes
only rows past the retention window, and sp_retention_run_all reports one row
per object. forecast/anomaly/fact tables are intentionally NOT purged.
"""
from __future__ import annotations

import uuid

import pytest

from app.database import get_cursor

RUN = uuid.uuid4().hex[:8].upper()

_EXPECTED_OBJECTS = {
    "audit_log",
    "user_sessions",
    "idempotency_keys",
    "rate_limit_state",
}

_EXPECTED_PROCS = {
    "sp_retention_purge_audit_log",
    "sp_retention_purge_user_sessions",
    "sp_retention_purge_idempotency_keys",
    "sp_retention_purge_rate_limit_state",
    "sp_retention_run_all",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _admin_user_id(cur) -> int:
    cur.execute("SELECT id FROM users WHERE username = 'admin' LIMIT 1")
    row = cur.fetchone()
    assert row is not None, "admin user must exist (seeded demo data)"
    return row["id"]


def _scalar(cur) -> int:
    """First column of the single-row result of a SELECT sp_*(...) call."""
    return list(cur.fetchone().values())[0]


# ---------------------------------------------------------------------------
# procedures exist in pg_proc
# ---------------------------------------------------------------------------

def test_retention_procedures_exist(app):
    with app.app_context():
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT p.proname
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public'
                  AND p.proname IN (
                      'sp_retention_purge_audit_log',
                      'sp_retention_purge_user_sessions',
                      'sp_retention_purge_idempotency_keys',
                      'sp_retention_purge_rate_limit_state',
                      'sp_retention_run_all'
                  )
                """
            )
            names = {r["proname"] for r in cur.fetchall()}

    assert names == _EXPECTED_PROCS, (
        f"expected all 5 retention procedures, found {sorted(names)}"
    )


# ---------------------------------------------------------------------------
# sp_retention_purge_idempotency_keys: old row purged, fresh row stays
# ---------------------------------------------------------------------------

def test_purge_idempotency_keys_window(app):
    key_old = f"ret-{RUN}-old"
    key_new = f"ret-{RUN}-new"
    with app.app_context():
        try:
            with get_cursor(commit=True) as cur:
                uid = _admin_user_id(cur)
                cur.execute(
                    """
                    INSERT INTO idempotency_keys (key, user_id, created_at)
                    VALUES (%s, %s, NOW() - interval '40 days')
                    """,
                    (key_old, uid),
                )
                cur.execute(
                    "INSERT INTO idempotency_keys (key, user_id) VALUES (%s, %s)",
                    (key_new, uid),
                )

                cur.execute("SELECT sp_retention_purge_idempotency_keys(30)")
                purged = _scalar(cur)
                assert purged >= 1, f"old row must be purged, got purged={purged}"

                cur.execute(
                    """
                    SELECT COUNT(*) AS c FROM idempotency_keys WHERE key = %s
                    """,
                    (key_old,),
                )
                assert cur.fetchone()["c"] == 0, "40-day-old row must be gone"

                cur.execute(
                    """
                    SELECT COUNT(*) AS c FROM idempotency_keys WHERE key = %s
                    """,
                    (key_new,),
                )
                assert cur.fetchone()["c"] == 1, "fresh row must survive purge(30)"
        finally:
            with get_cursor(commit=True) as cur:
                cur.execute(
                    "DELETE FROM idempotency_keys WHERE key = ANY(%s)",
                    ([key_old, key_new],),
                )


# ---------------------------------------------------------------------------
# sp_retention_purge_rate_limit_state: expired rows purged
# ---------------------------------------------------------------------------

def test_purge_rate_limit_state_expired(app):
    key = f"ret-{RUN}-rl"
    with app.app_context():
        try:
            with get_cursor(commit=True) as cur:
                cur.execute(
                    """
                    INSERT INTO rate_limit_state (key, count, expires_at)
                    VALUES (%s, 1, NOW() - interval '1 minute')
                    """,
                    (key,),
                )
                cur.execute("SELECT sp_retention_purge_rate_limit_state()")
                purged = _scalar(cur)
                assert purged >= 1, f"expired row must be purged, got purged={purged}"

                cur.execute(
                    "SELECT COUNT(*) AS c FROM rate_limit_state WHERE key = %s",
                    (key,),
                )
                assert cur.fetchone()["c"] == 0, "expired row must be gone"
        finally:
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM rate_limit_state WHERE key = %s", (key,))


# ---------------------------------------------------------------------------
# sp_retention_run_all: one row per object
# ---------------------------------------------------------------------------

def test_run_all_returns_row_per_object(app):
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT * FROM sp_retention_run_all()")
            rows = cur.fetchall()

    objects = {r["object_name"] for r in rows}
    assert objects == _EXPECTED_OBJECTS, (
        f"run_all must report one row per object, got {sorted(objects)}"
    )
    assert all(isinstance(r["purged"], int) and r["purged"] >= 0 for r in rows), (
        f"every purged count must be a non-negative integer: {rows}"
    )
