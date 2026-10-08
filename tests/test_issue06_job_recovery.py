"""RED-phase tests for Issue 06 — background job recovery / ETL in-flight guard.

Every test targets a consolidated review finding (F1-F5) and is expected to
FAIL against the current ``app/routes/ui.py``. backend-lead implements the
fixes; these tests then go green. Do NOT weaken them to get a pass.

Contract established by these tests (implementation must match):

* Lock: module-level ``_ETL_RUN_LOCK`` (``threading.Lock``) in
  ``app.routes.ui``. Acquired non-blocking in ``monitoring_run_etl`` BEFORE
  the worker thread is spawned; released in ``_run``'s ``finally``; consulted
  read-only by ``monitoring()`` for stale-``running`` detection. It must NOT
  be taken inside ``run_etl()`` — direct callers (bootstrap, CLI, the existing
  watermark tests) must keep working (see T06f2).
* Status rows: parameterized upsert into ``etl_warehouse_state``
  (``state_key`` PK, ``value TEXT``), following the ``etl.py:80-88``
  ``_write_state`` precedent:
    - ``etl_job_status``   -> ``running`` | ``success`` | ``failed``
      (``interrupted`` is surfaced at READ time only, never persisted)
    - ``etl_job_error``    -> ``_safe_error(e)`` output; cleared on success
    - ``warehouse_etl_ok`` -> persisted ``summary["warehouse_etl_ok"]`` —
      this resolves Issue 03's "warehouse_etl_ok has no UI consumer"
      follow-up: the row renders through the existing
      ``monitoring.html:184-190`` loop for free.
* ``_run`` must execute inside an app context captured in the route
  (mirror ``ui.py:73-76``) so the daemon thread can touch the DB (F1).
* Completion (success AND failure) calls ``monitoring_cache.invalidate("")``.
* Route shape must stay ``threading.Thread(target=_run, daemon=True).start()``
  with the target named ``_run``, so NEW-1's existing capture in
  ``tests/test_issue03_regressions.py`` keeps passing.

Scope: tests only — no production-code edits, no template/JS changes (so no
e2e, no asset-version bump). T-06g (429 burst) is intentionally NOT written:
it depends on F6 shipping a concrete ``@limiter.limit`` on the POST route —
add it conditionally alongside the limit value if F6 lands, rather than
encoding a guessed limit now.
"""
from __future__ import annotations

import re

import psycopg2
import pytest


# ---------------------------------------------------------------------------
# contract keys (single source of truth for backend-lead)
# ---------------------------------------------------------------------------

_STATUS_KEYS = ("etl_job_status", "etl_job_error", "warehouse_etl_ok")

_LEAKY_MESSAGE = (
    'connection to server at "db.example.com", port 5432\n'
    'FATAL:  password authentication failed for user "postgres"'
)


# ---------------------------------------------------------------------------
# helpers (patterns reused from test_issue03_regressions.py /
# test_frontend_mitigations.py)
# ---------------------------------------------------------------------------

def _read_state(cur, key: str):
    """Read a watermark from etl_state (T06f2 idempotency path)."""
    cur.execute("SELECT value FROM etl_state WHERE state_key = %s", (key,))
    row = cur.fetchone()
    return row["value"] if row else None


def _get_wh_state(cur, key: str):
    cur.execute(
        "SELECT value FROM etl_warehouse_state WHERE state_key = %s", (key,)
    )
    row = cur.fetchone()
    return row["value"] if row else None


def _set_wh_state(cur, key: str, value: str) -> None:
    """Upsert following etl.py:80-88 _write_state precedent."""
    cur.execute(
        """
        INSERT INTO etl_warehouse_state (state_key, value, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (state_key)
        DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """,
        (key, value),
    )


def _insert_movement(cur, reference: str, qty: int = 10) -> int:
      """Insert one movement and return its id (T06f2 watermark proof)."""
      cur.execute("SELECT id FROM products ORDER BY id LIMIT 1")
      row = cur.fetchone()
      assert row is not None, "no seeded products in test DB"
      cur.execute(
          """
          INSERT INTO movements (product_id, type, quantity, reference,
                                 notes, created_at)
          VALUES (%s, 'IN', %s, %s, 'issue06 regression', NOW())
          RETURNING id
          """,
          (row["id"], qty, reference),
      )
      return int(cur.fetchone()["id"])


def _healthy_etl(force: bool = False) -> dict:
    """Stand-in for etl_database: healthy run, warehouse layer OK."""
    return {
        "warehouse_etl_ok": True,
        "skipped": False,
        "incremental": False,
    }


def _session_client(app, username: str):
    """Authenticated client without POSTing /auth/login (10/min limiter is
    shared across the suite). Session-injection pattern from
    tests/test_frontend_mitigations.py."""
    from flask_login.utils import _create_identifier

    from app.repositories import UserRepository

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


def _install_thread_capture(monkeypatch) -> dict:
    """Capture the route's thread target instead of spawning a real daemon
    thread. Seam pattern from test_issue03_regressions.py NEW-1 (L454-471);
    also records ``daemon`` so the route shape stays locked. Bind the stub
    only into ui.py's namespace — patching the REAL threading module would
    break flask-limiter's internal Timer (it subclasses threading.Thread)."""
    import types as _types

    import app.routes.ui as ui_module

    captured: dict = {}

    class _CaptureThread:
        def __init__(self, target=None, daemon=None, *args, **kwargs):
            if target is not None:
                captured["target"] = target
                captured["daemon"] = daemon

        def start(self):
            pass

        def join(self, *args, **kwargs):
            pass

    monkeypatch.setattr(
        ui_module, "threading", _types.SimpleNamespace(Thread=_CaptureThread)
    )
    return captured


def _session_flashes(client) -> list:
    with client.session_transaction() as sess:
        return [tuple(f) for f in sess.get("_flashes", [])]


def _etl_status_cell(html: str, key: str):
    """Extract the rendered value cell for an etl_warehouse_state row from
    monitoring.html:184-190 (<td><code>key</code></td>\\s*<td>value</td>)."""
    m = re.search(
        rf"<code>{re.escape(key)}</code></td>\s*<td>(.*?)</td>", html, re.S
    )
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# fixture hygiene (critical): one test's held lock / seeded status row /
# warm monitoring cache must never poison the next test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _etl_job_hygiene(app):
    import app.routes.ui as ui_module
    from app.database import get_cursor
    from app.extensions import limiter
    from app.utils.cache import monitoring_cache

    def _reset_state():
        lock = getattr(ui_module, "_ETL_RUN_LOCK", None)
        if lock is not None and lock.locked():
            lock.release()
        monitoring_cache.invalidate("")  # 60s TTL would mask seeded rows
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute(
                    "DELETE FROM etl_warehouse_state WHERE state_key = ANY(%s)",
                    (list(_STATUS_KEYS),),
                )

    # F6 may add a limiter to this route later; keep our handful of POSTs
    # order-independent either way (same reset pattern as test_auth_lockout).
    limiter.reset()
    _reset_state()
    yield
    limiter.reset()
    _reset_state()


# ---------------------------------------------------------------------------
# T-06a - F1 CRITICAL: captured _run must execute with an app context
# ---------------------------------------------------------------------------

def test_t06a_captured_run_target_executes_with_app_context(app, monkeypatch):
    """F1: ``_run`` (ui.py ~L2325) has no app context, so the real daemon
    thread dies on ``current_app`` the moment it touches the DB — feature is
    dead-on-arrival. Fix = 2 lines mirroring ui.py:73-76: capture
    ``_app = current_app._get_current_object()`` in the route, wrap ``_run``'s
    body in ``with _app.app_context():``.

    Also locks the NEW-1 capture seam: target named ``_run``, spawned via
    ``threading.Thread(target=_run, daemon=True).start()``.
    """
    from flask import has_app_context

    import app.database.connection as conn_module
    import app.routes.ui as ui_module

    seen: dict = {}

    def _probe_etl(force: bool = False) -> dict:
        seen["called"] = True
        seen["ctx"] = has_app_context()
        return _healthy_etl(force)

    # _run resolves etl_database via the route-local import at POST time,
    # so patching the module attribute before the POST is the seam.
    monkeypatch.setattr(conn_module, "etl_database", _probe_etl)
    captured = _install_thread_capture(monkeypatch)
    client = _session_client(app, "admin")

    resp = client.post("/monitoring/run-etl", follow_redirects=False)
    assert resp.status_code in (301, 302, 303), (
        f"run-etl route did not respond with redirect: {resp.status_code}"
    )

    # Route-shape guards (NEW-1 seam must keep working) — green today.
    assert "target" in captured, "route did not build the _run thread target"
    target = captured["target"]
    assert target.__name__ == "_run", (
        f"thread target must stay named _run for NEW-1's capture seam, "
        f"got {target.__name__!r}"
    )
    assert captured.get("daemon") is True, "route must spawn daemon=True"

    # The daemon thread starts with NO ambient Flask context — invoke the
    # captured target bare, exactly as the real thread would.
    target()

    assert seen.get("called") is True, "etl_database was never invoked by _run"
    assert seen.get("ctx") is True, (
        "F1: _run executed without an application context — the background "
        "thread target must wrap its body in `with _app.app_context():` "
        "(capture _app = current_app._get_current_object() in the route, "
        "mirroring ui.py:73-76)"
    )

    lock = getattr(ui_module, "_ETL_RUN_LOCK", None)
    if lock is not None:
        assert not lock.locked(), "F2: _run must release the in-flight lock in finally"


# ---------------------------------------------------------------------------
# T-06b - F2 HIGH: concurrent POST while a job is in flight is a no-op
# ---------------------------------------------------------------------------

def test_t06b_concurrent_run_etl_request_is_noop_when_in_flight(app, monkeypatch):
    """F2: no in-flight guard today — concurrent POST /monitoring/run-etl =
    double-TRUNCATE race. Fix: non-blocking ``_ETL_RUN_LOCK.acquire`` in the
    route BEFORE spawning; on failure flash info and return WITHOUT spawning
    a second thread and WITHOUT touching status rows.

    Lock manipulation (we hold the lock, then a single POST) — deliberately
    NOT a second real POST, so the shared limiter is not the variable under
    test.
    """
    import app.routes.ui as ui_module

    lock = getattr(ui_module, "_ETL_RUN_LOCK", None)
    assert lock is not None, (
        "F2: module-level _ETL_RUN_LOCK missing from app.routes.ui — the "
        "in-flight guard does not exist yet"
    )

    captured = _install_thread_capture(monkeypatch)
    client = _session_client(app, "admin")

    assert lock.acquire(blocking=False), "lock unexpectedly held at test start"
    try:
        resp = client.post("/monitoring/run-etl", follow_redirects=False)
        assert resp.status_code in (301, 302, 303), (
            f"no-op path must still redirect, got {resp.status_code}"
        )

        # Primary: no second worker spawned (no second TRUNCATE possible).
        assert "target" not in captured, (
            "F2: POST spawned a second ETL thread while one was in flight"
        )

        # Secondary: info-flash no-op, success reserved for an actual spawn.
        cats = [c for c, _ in _session_flashes(client)]
        assert "info" in cats, (
            f"F2: no-op path must flash info, got flashes {cats}"
        )
        assert "success" not in cats, (
            f"F2: no-op path must not claim the rebuild started, got {cats}"
        )
    finally:
        if lock.locked():
            lock.release()


# ---------------------------------------------------------------------------
# T-06c - F3+M5 MED: crashed run persists failed status + sanitized error
# ---------------------------------------------------------------------------

def test_t06c_failed_run_persists_failed_status_with_sanitized_error(
    app, monkeypatch
):
    """F3: no job-status persistence today — a background crash is only a
    log line. Fix: upsert ``etl_job_status='failed'`` and
    ``etl_job_error=_safe_error(e)`` (etl.py:345-350) into
    ``etl_warehouse_state``. For OperationalError that is the CLASS NAME
    only — the raw libpq message embeds host/user and must never persist.
    """
    import app.database.connection as conn_module
    import app.routes.ui as ui_module

    def _boom(force: bool = False) -> dict:
        raise psycopg2.OperationalError(_LEAKY_MESSAGE)

    monkeypatch.setattr(conn_module, "etl_database", _boom)
    captured = _install_thread_capture(monkeypatch)
    client = _session_client(app, "admin")

    resp = client.post("/monitoring/run-etl", follow_redirects=False)
    assert resp.status_code in (301, 302, 303)
    assert "target" in captured, "route did not build the _run thread target"

    captured["target"]()  # run the failure path bare (no ambient context)

    from app.database import get_cursor

    with app.app_context():
        with get_cursor() as cur:
            status = _get_wh_state(cur, "etl_job_status")
            err = _get_wh_state(cur, "etl_job_error")

    assert status == "failed", (
        f"F3: expected etl_job_status 'failed' after a crashed run, "
        f"got {status!r}"
    )
    assert err is not None and str(err) != "", (
        "F3: sanitized error must be persisted on failure"
    )
    assert "db.example.com" not in str(err), (
        f"F3: persisted error leaked connection host: {err!r}"
    )
    assert 'user "postgres"' not in str(err), (
        f"F3: persisted error leaked connection user: {err!r}"
    )
    assert str(err) == "OperationalError", (
        f"persisted error must be exactly _safe_error(e) output (class name "
        f"for OperationalError), got {err!r}"
    )

    lock = getattr(ui_module, "_ETL_RUN_LOCK", None)
    if lock is not None:
        assert not lock.locked(), (
            "F2: _run must release the in-flight lock in finally — also on "
            "the failure path"
        )


# ---------------------------------------------------------------------------
# T-06d - F3+M5 MED: success path persists status, clears error,
# invalidates monitoring_cache at completion
# ---------------------------------------------------------------------------

def test_t06d_successful_run_persists_success_status_and_invalidates_cache(
    app, monkeypatch
):
    """F3+M5: healthy run must persist ``etl_job_status='success'`` +
    ``warehouse_etl_ok`` (resolves Issue 03's no-UI-consumer follow-up —
    the row renders through monitoring.html:184-190), clear any stale
    ``etl_job_error``, and call ``monitoring_cache.invalidate("")`` at
    COMPLETION (the route's own invalidate fires during the POST, before
    the spy below exists, so only completion-time calls are recorded).
    """
    import app.database.connection as conn_module
    import app.routes.ui as ui_module

    monkeypatch.setattr(conn_module, "etl_database", _healthy_etl)
    captured = _install_thread_capture(monkeypatch)
    client = _session_client(app, "admin")

    resp = client.post("/monitoring/run-etl", follow_redirects=False)
    assert resp.status_code in (301, 302, 303)
    assert "target" in captured, "route did not build the _run thread target"

    # Spy on the shared cache INSTANCE so both ui-module-global and
    # fresh-import references see it.
    invalidate_calls: list = []
    real_invalidate = ui_module.monitoring_cache.invalidate

    def _spy(prefix: str = "") -> int:
        invalidate_calls.append(prefix)
        return real_invalidate(prefix)

    monkeypatch.setattr(ui_module.monitoring_cache, "invalidate", _spy)

    # Invoke bare — _run must open its own context (F1) to persist rows.
    captured["target"]()

    from app.database import get_cursor

    with app.app_context():
        with get_cursor() as cur:
            status = _get_wh_state(cur, "etl_job_status")
            ok = _get_wh_state(cur, "warehouse_etl_ok")
            err = _get_wh_state(cur, "etl_job_error")

    assert status == "success", (
        f"F3: expected etl_job_status 'success' after a healthy run, "
        f"got {status!r}"
    )
    assert ok is not None and str(ok).strip().lower() in ("true", "1"), (
        f"F3+Issue03: warehouse_etl_ok must be persisted on success so it "
        f"renders on /monitoring, got {ok!r}"
    )
    assert err is None or str(err) == "", (
        f"F3: etl_job_error must be cleared on success, got {err!r}"
    )
    assert "" in invalidate_calls, (
        f"F3: monitoring_cache.invalidate('') must run at job completion, "
        f"calls={invalidate_calls}"
    )

    lock = getattr(ui_module, "_ETL_RUN_LOCK", None)
    if lock is not None:
        assert not lock.locked(), "F2: _run must release the in-flight lock in finally"


# ---------------------------------------------------------------------------
# T-06e - F4 MED: stale-running detection (lock-as-oracle at read time)
# ---------------------------------------------------------------------------

def test_t06e_stale_running_detection_uses_lock_as_oracle(app):
    """F4: a ``running`` row whose owning process died must not read as
    ``running`` forever. Oracle = the module lock:
      * row=running, lock NOT held -> surface ``interrupted`` at read
        (rendered only; the persisted row stays ``running``),
      * row=running, lock held     -> still ``running``.

    GET /monitoring renders through monitoring.html:184-190; templates are
    untouched, so the transformation happens in the route's ``_load``.
    """
    import app.routes.ui as ui_module
    from app.database import get_cursor
    from app.utils.cache import monitoring_cache

    client = _session_client(app, "admin")

    with app.app_context():
        with get_cursor(commit=True) as cur:
            _set_wh_state(cur, "etl_job_status", "running")

    # Case A: dead running row (lock not held) -> interrupted.
    monitoring_cache.invalidate("")
    resp = client.get("/monitoring")
    assert resp.status_code == 200, f"/monitoring returned {resp.status_code}"
    html = resp.get_data(as_text=True)
    cell = _etl_status_cell(html, "etl_job_status")
    assert cell is not None, (
        "etl_job_status row not rendered on /monitoring — is the seeded row "
        "visible to _load (warm cache or sp_monitor_* failure)?"
    )
    assert cell == "interrupted", (
        f"F4: dead running row must surface as 'interrupted', rendered {cell!r}"
    )

    # Pair case: lock held + running -> still running.
    lock = getattr(ui_module, "_ETL_RUN_LOCK", None)
    assert lock is not None, (
        "F2/F4: module-level _ETL_RUN_LOCK missing from app.routes.ui"
    )
    assert lock.acquire(blocking=False), "lock unexpectedly held at test start"
    try:
        monitoring_cache.invalidate("")  # bust case A's cached payload
        resp = client.get("/monitoring")
        assert resp.status_code == 200, f"/monitoring returned {resp.status_code}"
        html = resp.get_data(as_text=True)
        cell = _etl_status_cell(html, "etl_job_status")
        assert cell == "running", (
            f"F4: live running row must stay 'running' while the lock is "
            f"held, rendered {cell!r}"
        )
    finally:
        if lock.locked():
            lock.release()


# ---------------------------------------------------------------------------
# T-06f1 - recovery: re-run after failed flips the row to success
# ---------------------------------------------------------------------------

def test_t06f1_recovery_rerun_after_failed_persists_success(app, monkeypatch):
    """F3 recovery: after a ``failed`` row exists, a fresh route-triggered
    run (healthy mocked etl_database) must overwrite it with ``success``,
    clear the stale error, and persist ``warehouse_etl_ok`` — i.e. the UI
    recovers from a crash without manual state surgery.
    """
    import app.database.connection as conn_module
    import app.routes.ui as ui_module
    from app.database import get_cursor

    # Seed a crashed job's leftovers.
    with app.app_context():
        with get_cursor(commit=True) as cur:
            _set_wh_state(cur, "etl_job_status", "failed")
            _set_wh_state(cur, "etl_job_error", "previous crash")

    monkeypatch.setattr(conn_module, "etl_database", _healthy_etl)
    captured = _install_thread_capture(monkeypatch)
    client = _session_client(app, "admin")

    resp = client.post("/monitoring/run-etl", follow_redirects=False)
    assert resp.status_code in (301, 302, 303)
    assert "target" in captured, "route did not build the _run thread target"

    captured["target"]()  # bare invoke — _run opens its own context (F1)

    with app.app_context():
        with get_cursor() as cur:
            status = _get_wh_state(cur, "etl_job_status")
            ok = _get_wh_state(cur, "warehouse_etl_ok")
            err = _get_wh_state(cur, "etl_job_error")

    assert status == "success", (
        f"F3: recovery run must flip etl_job_status to 'success', got {status!r}"
    )
    assert ok is not None and str(ok).strip().lower() in ("true", "1"), (
        f"F3+Issue03: warehouse_etl_ok must be persisted on recovery, got {ok!r}"
    )
    assert err is None or str(err) == "", (
        f"F3: stale etl_job_error must be cleared on recovery, got {err!r}"
    )

    lock = getattr(ui_module, "_ETL_RUN_LOCK", None)
    if lock is not None:
        assert not lock.locked(), "F2: _run must release the in-flight lock in finally"


# ---------------------------------------------------------------------------
# T-06f2 - F2 placement guard: direct etl_database() calls bypass the
# route lock (keeps issue03 T1/T1b watermark path working)
# ---------------------------------------------------------------------------

def test_t06f2_direct_etl_database_call_bypasses_route_lock(app):
    """F2 placement: the guard lives in the route/thread, NOT inside
    ``run_etl()`` — direct callers (bootstrap at startup, CLI, and the
    existing watermark tests T1/T1b in test_issue03_regressions.py) must not
    collide with an in-flight route job. With the route lock HELD, a direct
    ``etl_database(force=False)`` must run to completion (not block, not
    skip), advance the watermark past a fresh movement, and must not release
    a lock it does not own.
    """
    import app.routes.ui as ui_module
    from app.database import get_cursor
    from app.database.connection import etl_database

    lock = getattr(ui_module, "_ETL_RUN_LOCK", None)
    assert lock is not None, (
        "F2: module-level _ETL_RUN_LOCK missing from app.routes.ui — direct-"
        "call isolation cannot be verified without the guard existing"
    )

    with app.app_context():
        assert lock.acquire(blocking=False), "lock unexpectedly held at test start"
        try:
            with get_cursor(commit=True) as cur:
                new_id = _insert_movement(cur, "TEST-ISSUE06-F2")
            with get_cursor() as cur:
                watermark_before = int(_read_state(cur, "last_movement_id") or 0)

            # The bootstrap/CLI/watermark-test path, invoked while a route
            # job (us) is "in flight".
            summary = etl_database(force=False)

            assert summary.get("skipped") is False, (
                f"F2: direct etl_database() was short-circuited while the "
                f"route lock was held (summary={summary}) — the guard must "
                f"NOT live in run_etl()"
            )
            with get_cursor() as cur:
                watermark_after = int(_read_state(cur, "last_movement_id") or 0)
            assert watermark_after >= new_id, (
                f"F2: watermark did not advance past movement {new_id} "
                f"({watermark_before} -> {watermark_after}) — the direct run "
                f"was blocked or skipped by the route lock"
            )
            assert lock.locked(), (
                "F2: run_etl() released the route's in-flight lock it does "
                "not own"
            )
        finally:
            if lock.locked():
                lock.release()


# ---------------------------------------------------------------------------
# T-06g — NOT WRITTEN (conditional on F6)
# ---------------------------------------------------------------------------
# If backend-lead ships F6 (`@limiter.limit(...)` on POST /monitoring/run-etl),
# add a 429-burst test alongside it using the SHIPPED limit value plus
# `limiter.reset()` in the body (pattern: test_frontend_mitigations L249-253).
# Encoding a guessed limit now would be brittle; F6 is non-blocking.
