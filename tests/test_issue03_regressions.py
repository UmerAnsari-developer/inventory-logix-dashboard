"""RED-phase regression tests for Issue 03 round 2 (ETL process failure handling).

Every test here targets a consolidated review finding (F1-F7) and is expected
to FAIL against the current ``app/database/etl.py``. backend-lead implements
the fixes; these tests then go green. Do NOT weaken them to get a pass.

Note on the existing suites: the ``watermark_after >= initial_watermark``
assertions in ``tests/test_etl_failure_handling.py`` and
``tests/test_etl_failure_handling_new.py`` remain TRUE after the F1 fix (they
become equalities), but they are weak enough to mask F1 today. Recommend
tightening them to ``==`` in a follow-up - not done here, because existing
tests are frozen during the red phase.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import psycopg2
import pytest


# ---------------------------------------------------------------------------
# helpers (patterns reused from the existing ETL test suites)
# ---------------------------------------------------------------------------

def _read_state(cur, key: str):
    cur.execute("SELECT value FROM etl_state WHERE state_key = %s", (key,))
    row = cur.fetchone()
    return row["value"] if row else None


def _insert_test_movement(cur, reference: str, qty: int = 10) -> None:
      """Insert one movement so a follow-up incremental run is not skipped."""
      cur.execute("SELECT id FROM products ORDER BY id LIMIT 1")
      row = cur.fetchone()
      cur.execute(
          """
          INSERT INTO movements (product_id, type, quantity, reference, notes, created_at)
          VALUES (%s, 'IN', %s, %s, 'issue03 regression', NOW())
          """,
          (row["id"], qty, reference),
      )


def _warehouse_etl_fails(conn=None):
    """Stand-in for _run_warehouse_etl that fails the way the real one does
    (rollback, then raise) without touching the warehouse procedures."""
    if conn is not None:
        conn.rollback()
    raise RuntimeError("simulated warehouse ETL failure")


# ---------------------------------------------------------------------------
# T1 - F1 CRITICAL: failed incremental run must not advance the watermark
# ---------------------------------------------------------------------------

def test_t1_failed_incremental_run_keeps_watermark_unchanged(app):
    """F1: stages 1-3 checkpoint the incoming last_id; only stage 4 advances
    to max_id. Today stage 2 commits max_id before the fact stages run, so a
    stage-3 failure permanently skips those movements on the next run."""
    from app.database.connection import etl_database
    from app.database import get_cursor
    import app.database.etl as etl_module

    with app.app_context():
        # Baseline full rebuild -> watermark == max_id at this moment.
        etl_database(force=True)

        with get_cursor() as cur:
            watermark_before = int(_read_state(cur, "last_movement_id"))

        # New movement so the incremental run is not skipped (max_id > watermark).
        with get_cursor(commit=True) as cur:
            _insert_test_movement(cur, "TEST-F1-WATERMARK")

        original_build = etl_module._build_movement_facts

        def failing_build_movement_facts(*args, **kwargs):
            raise Exception("Simulated stage-3 fact failure (F1)")

        etl_module._build_movement_facts = failing_build_movement_facts
        try:
            with pytest.raises(Exception, match="Simulated stage-3 fact failure"):
                etl_database(force=False)
        finally:
            etl_module._build_movement_facts = original_build

        with get_cursor() as cur:
            watermark_after = int(_read_state(cur, "last_movement_id"))

        # STRICT equality: the failed run must leave the watermark untouched
        # so the new movement is replayed on the next run. Currently stage 2
        # writes max_id and commits -> watermark_after > watermark_before.
        assert watermark_after == watermark_before, (
            f"watermark advanced on failed run: before={watermark_before} "
            f"after={watermark_after} (F1: stage checkpoint must replay last_id)"
        )


# ---------------------------------------------------------------------------
# T2 - F2 HIGH: force=True must not permanently lose fact_audit_daily history
# Fix strategy under test: (B) reset etl_warehouse_state['last_audit_daily_at']
# in the SAME transaction as the TRUNCATE. etl_load_audit_daily
# (etl_procedures.sql) then sees a missing state row, defaults v_last to
# '2024-01-01', and rebuilds full history from audit_log. Strategy (A) cannot
# preserve the rows: TRUNCATE ... without CASCADE fails unless every table
# FK-referencing dim_date (fact_audit_daily, fact_product_daily) is itself in
# the truncate list, which would wipe them anyway.
# ---------------------------------------------------------------------------

def test_t2_force_rebuild_preserves_fact_audit_daily_history(app):
    """F2 (fix B): after force=True, an old-day audit marker must still exist
    in fact_audit_daily."""
    from app.database.connection import etl_database
    from app.database import get_cursor

    old_day = (date.today() - timedelta(days=10)).isoformat()

    with app.app_context():
        # Baseline: normalise dims/facts and set last_audit_daily_at = today.
        etl_database(force=True)

        # Pin the watermark deterministically so a current-code reload is
        # guaranteed to skip the old day (harmless after fix B: the fix
        # resets this row inside the TRUNCATE transaction).
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO etl_warehouse_state (state_key, value, updated_at)
                VALUES ('last_audit_daily_at', %s, NOW())
                ON CONFLICT (state_key)
                DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (date.today().isoformat(),),
            )

        # Marker: an audit event on a day strictly BEFORE the watermark.
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT id FROM users ORDER BY id LIMIT 1")
            uid = cur.fetchone()["id"]
            cur.execute(
                """
                INSERT INTO audit_log (user_id, action, target_type, target_id,
                                       detail, ip_address, created_at)
                VALUES (%s, 'TEST_OLD_DAY_MARKER', 'test_marker', NULL,
                        '{}'::jsonb, '127.0.0.1',
                        CAST(%s || ' 12:00:00' AS timestamp))
                """,
                (uid, old_day),
            )

        # force=True TRUNCATEs dim_date -> CASCADE wipes fact_audit_daily.
        # Current code: etl_load_audit_daily only reloads days >= watermark
        # (today) -> the marker is gone forever. Fix B resets the watermark
        # in the TRUNCATE transaction -> full history reload from audit_log.
        etl_database(force=True)

        with get_cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS c FROM fact_audit_daily
                WHERE date_key = %s AND action = 'TEST_OLD_DAY_MARKER'
                """,
                (old_day,),
            )
            count = cur.fetchone()["c"]

        assert count >= 1, (
            f"fact_audit_daily lost old-day history across force=True "
            f"(marker rows for {old_day} = {count}) - F2"
        )


# ---------------------------------------------------------------------------
# T3 - F5 MED: last_run_at must be committed before warehouse ETL runs
# ---------------------------------------------------------------------------

def test_t3_last_run_at_survives_warehouse_etl_failure(app):
    """F5: if warehouse ETL fails, last_run_at written just before it must
    still be committed. Today the write is only committed as a side effect of
    _run_warehouse_etl's commit; its rollback discards it."""
    from app.database.connection import etl_database
    from app.database import get_cursor
    import app.database.etl as etl_module

    with app.app_context():
        # Clean slate so "set vs not set" is meaningful.
        with get_cursor(commit=True) as cur:
            cur.execute("DELETE FROM etl_state WHERE state_key = 'last_run_at'")

        original = etl_module._run_warehouse_etl
        etl_module._run_warehouse_etl = _warehouse_etl_fails
        try:
            # Warehouse failure is caught -> run reports success (summary).
            summary = etl_database(force=True)
        finally:
            etl_module._run_warehouse_etl = original

        assert summary["skipped"] is False  # the run really executed

        # Read via a fresh (pooled) cursor: only committed state is visible.
        with get_cursor() as cur:
            row_value = _read_state(cur, "last_run_at")

        assert row_value is not None, (
            "last_run_at missing after warehouse-ETL failure - F5: write must "
            "be committed immediately, before _run_warehouse_etl"
        )
        assert row_value == date.today().isoformat()


# ---------------------------------------------------------------------------
# T4 - F6 MED: warehouse ETL outcome must be observable in the summary
# ---------------------------------------------------------------------------

def test_t4_summary_reports_warehouse_etl_ok(app):
    """F6: summary['warehouse_etl_ok'] is False when the warehouse ETL fails
    and True on a healthy run. Today the failure is only a warning and the
    run reports success with no flag at all."""
    from app.database.connection import etl_database
    import app.database.etl as etl_module

    with app.app_context():
        original = etl_module._run_warehouse_etl
        etl_module._run_warehouse_etl = _warehouse_etl_fails
        try:
            failed_summary = etl_database(force=True)
        finally:
            etl_module._run_warehouse_etl = original

        assert failed_summary.get("warehouse_etl_ok") is False, (
            "warehouse_etl_ok must be False when the warehouse ETL raised - F6"
        )

        ok_summary = etl_database(force=True)
        assert ok_summary.get("warehouse_etl_ok") is True, (
            "warehouse_etl_ok must be True on a healthy run - F6"
        )


# ---------------------------------------------------------------------------
# T5 - F7 MED: DB-connection-class errors must not leak host/user in logs
# ---------------------------------------------------------------------------

def test_t5_operational_error_logs_do_not_leak_connection_details(
    app, monkeypatch, caplog
):
    """F7: etl.py log lines on OperationalError paths must log only the
    exception class name - no libpq message text (host/port/user), no
    exc_info for DB-connection-class errors."""
    from app.database.connection import etl_database
    from app.database import get_cursor
    import app.database.etl as etl_module

    leaky_message = (
        'could not connect to server "db.example.com", port 5432\n'
        'FATAL:  password authentication failed for user "postgres"'
    )

    with app.app_context():
        # Baseline so the failing run takes the incremental path.
        etl_database(force=True)
        with get_cursor(commit=True) as cur:
            _insert_test_movement(cur, "TEST-F7-LOGS")

        def failing_build_dims(*args, **kwargs):
            raise psycopg2.OperationalError(leaky_message)

        # run_etl resolves module globals at call time; OperationalError is
        # the retried type, so patch sleep to skip the 1s+2s backoff.
        monkeypatch.setattr(etl_module, "_build_dims", failing_build_dims)
        monkeypatch.setattr("time.sleep", lambda _s: None)

        with caplog.at_level(logging.DEBUG, logger="app.database.etl"):
            with pytest.raises(psycopg2.OperationalError):
                etl_database(force=False)

        # Scope to etl.py's logger only (connection.py residual is Issue 01,
        # explicitly out of scope for this finding).
        etl_logs = "\n".join(
            record.getMessage()
            for record in caplog.records
            if record.name == "app.database.etl"
        )

    assert "db.example.com" not in etl_logs, (
        "etl.py leaked connection host into logs - F7"
    )
    assert 'user "postgres"' not in etl_logs, (
        "etl.py leaked connection user into logs - F7"
    )
    assert "OperationalError" in etl_logs, (
        "etl.py logs must identify the error by class name - F7"
    )


# ---------------------------------------------------------------------------
# T6 - F3 HIGH: _parse_warehouse debug lines clobber the trimmed city
# ---------------------------------------------------------------------------

def test_t6_parse_warehouse_city_not_clobbered():
    """F3: lines 53-54 ('# This is a test' / 'city = body or "Unknown"')
    overwrite the trimmed city from line 52. 'WH-Pune' must parse to city
    'Pune', not to the raw body 'WH-Pune'."""
    from app.database.etl import _parse_warehouse

    code, city, region = _parse_warehouse("WH-Pune")
    assert city == "Pune"       # currently 'WH-Pune' (debug line 54 clobbers)
    assert code == "WH-PUN"     # currently 'WH-WH-'
    assert region == "Central"  # currently 'General'

    # Bare 'WH-' still falls back to 'Unknown' once line 54 is removed.
    _, bare_city, _ = _parse_warehouse("WH-")
    assert bare_city == "Unknown"


# ---------------------------------------------------------------------------
# F4 - MED: stage rollback on a dead connection must not mask the real error
# ---------------------------------------------------------------------------

def test_f4_failed_rollback_does_not_mask_original_stage_error(app, monkeypatch):
    """F4 (minimum fix): every stage 'conn.rollback()' must be guarded, so a
    rollback that raises (dead connection) cannot replace the original stage
    exception. Proxy conn below simulates that: cursor/commit/close work,
    rollback raises InterfaceError."""
    from app.database.connection import etl_database
    from app.database import get_cursor
    import app.database.etl as etl_module

    class _DeadRollbackConn:
        def __init__(self, real):
            self._real = real

        def cursor(self, *args, **kwargs):
            return self._real.cursor(*args, **kwargs)

        def commit(self):
            return self._real.commit()

        def rollback(self):
            raise psycopg2.InterfaceError("connection closed: rollback impossible")

        def close(self):
            return self._real.close()

    with app.app_context():
        etl_database(force=True)

        with get_cursor(commit=True) as cur:
            _insert_test_movement(cur, "TEST-F4-ROLLBACK")

        real_open = etl_module._open_conn
        monkeypatch.setattr(
            etl_module, "_open_conn", lambda: _DeadRollbackConn(real_open())
        )

        def failing_build_movement_facts(*args, **kwargs):
            raise ValueError("ORIGINAL stage failure (F4)")

        monkeypatch.setattr(
            etl_module, "_build_movement_facts", failing_build_movement_facts
        )

        # Today: stage handler's bare conn.rollback() raises InterfaceError,
        # which REPLACES the ValueError -> pytest.raises never sees it.
        # After fix: rollback failure is swallowed, ValueError propagates.
        with pytest.raises(ValueError, match="ORIGINAL stage failure"):
            etl_database(force=False)


# ---------------------------------------------------------------------------
# T6b - B1 HIGH (pass-2): F3 fix removed the else fallback in _parse_warehouse
# ---------------------------------------------------------------------------

def test_t6b_legacy_warehouse_names_parse_without_unbound_error():
    """B1: the F3 fix deleted the ``else: city = body or "Unknown"`` branch.
    Legacy names with no ``WH-`` prefix leave ``city`` unbound, so the
    ``_REGION_HINT.get(city, ...)`` line raises UnboundLocalError.
    Expected values derived from the baseline in ``app/database/etl.py.bak``
    (quoted in the pass-2 handoff), not guessed:

    - ``"Warehouse 01 - Pune"`` -> body ``"Pune"`` after the ``" - "`` split;
      city ``"Pune"``; digits ``"01"`` -> code ``"WH01"``; region ``"Central"``.
    - ``"Mumbai"`` -> body ``"Mumbai"``; city ``"Mumbai"``; digits ``"" ->
      "00"`` -> code ``"WH00"``; region ``"West"``.
    """
    from app.database.etl import _parse_warehouse

    assert _parse_warehouse("Warehouse 01 - Pune") == ("WH01", "Pune", "Central")
    assert _parse_warehouse("Mumbai") == ("WH00", "Mumbai", "West")


# ---------------------------------------------------------------------------
# NEW-1 - B2 MED (security pass-2): Run-ETL background wrapper logs raw exc
# ---------------------------------------------------------------------------

def test_new1_run_etl_background_failure_logs_do_not_leak(
    app, monkeypatch, caplog
):
    """NEW-1: ``monitoring_run_etl``'s background ``_run`` wrapper logs
    ``"Background ETL failed: %s"`` with the raw exception (ui.py ~L2329).
    An OperationalError there embeds libpq host/user text into logs a manager
    can read at /admin/logs. The line must log only the exception class name
    (``type(e).__name__`` / ``_safe_error``)."""

    import app.database.connection as conn_module
    import app.routes.ui as ui_module
    from flask_login.utils import _create_identifier

    from app.repositories import UserRepository

    leaky_message = (
        'connection to server at "db.example.com", port 5432 '
        'failed for user "postgres"'
    )

    def raise_operational(force: bool = False) -> dict:
        raise psycopg2.OperationalError(leaky_message)

    # _run does `from ..database.connection import etl_database` at call time,
    # so patching the module attribute is the seam.
    monkeypatch.setattr(conn_module, "etl_database", raise_operational)

    # Session login without POSTing /auth/login (10/min limiter is shared
    # across the suite). Pattern from tests/test_frontend_mitigations.py.
    with app.app_context():
        user = UserRepository.find_by_username("admin")
        assert user is not None, "missing user admin"
        uid = user.id

    client = app.test_client()
    ident_box: dict = {}

    def _capture_ident():
        ident_box["id"] = _create_identifier()

    app.before_request_funcs.setdefault(None, []).append(_capture_ident)
    try:
        probe = client.get("/static/img/favicon.svg")
        assert probe.status_code == 200, "identifier probe request failed"
    finally:
        app.before_request_funcs[None].remove(_capture_ident)

    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
        sess["_id"] = ident_box["id"]

    # Capture the thread target instead of spawning a real daemon thread;
    # _run is invoked synchronously under caplog below. Bind the stub only
    # into ui.py's namespace — patching the REAL threading module would break
    # flask-limiter's internal Timer (it subclasses threading.Thread).
    captured: dict = {}

    class _CaptureThread:
        def __init__(self, target=None, daemon=None, *args, **kwargs):
            if target is not None:
                captured["target"] = target

        def start(self):
            pass

        def join(self, *args, **kwargs):
            pass

    import types as _types

    monkeypatch.setattr(
        ui_module, "threading", _types.SimpleNamespace(Thread=_CaptureThread)
    )

    resp = client.post("/monitoring/run-etl", follow_redirects=False)
    assert resp.status_code in (301, 302, 303), (
        f"run-etl route did not respond with redirect: {resp.status_code}"
    )
    assert "target" in captured, "route did not build the _run thread target"

    with caplog.at_level(logging.WARNING, logger="app.routes.ui"):
        captured["target"]()  # run _run() here; its except swallows the raise

    ui_logs = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name == "app.routes.ui"
    )

    assert "db.example.com" not in ui_logs, (
        "ui.py leaked connection host into Background ETL failure log - NEW-1"
    )
    assert 'user "postgres"' not in ui_logs, (
        "ui.py leaked connection user into Background ETL failure log - NEW-1"
    )
    assert "OperationalError" in ui_logs, (
        "Background ETL failure log must identify the error by class name - NEW-1"
    )


# ---------------------------------------------------------------------------
# T1b - B3 LOW (pass-2): stage-4 failure keeps watermark; movement replays
# ---------------------------------------------------------------------------

def test_t1b_stage4_failure_keeps_watermark_and_replays(app, monkeypatch):
    """B3: same contract as T1 but targeting stage 4. Stage 4
    (``_build_inventory_facts``) is the only stage that writes ``max_id``,
    and only after its own commit — a stage-4 failure must leave the
    watermark at the stage-3 checkpoint (incoming ``last_id``) so the new
    movement replays on the next run."""
    from app.database.connection import etl_database
    from app.database import get_cursor
    import app.database.etl as etl_module

    with app.app_context():
        # Baseline full rebuild -> watermark == max_id at this moment.
        etl_database(force=True)

        with get_cursor() as cur:
            watermark_before = int(_read_state(cur, "last_movement_id"))

        # New movement so the incremental run is not skipped.
        with get_cursor(commit=True) as cur:
            _insert_test_movement(cur, "TEST-T1B-STAGE4")

        original_build = etl_module._build_inventory_facts

        def failing_build_inventory_facts(*args, **kwargs):
            raise Exception("Simulated stage-4 inventory fact failure (B3)")

        etl_module._build_inventory_facts = failing_build_inventory_facts
        try:
            with pytest.raises(Exception, match="Simulated stage-4"):
                etl_database(force=False)
        finally:
            etl_module._build_inventory_facts = original_build

        with get_cursor() as cur:
            watermark_after = int(_read_state(cur, "last_movement_id"))

        # STRICT equality: stage 4 must not have written max_id on failure.
        assert watermark_after == watermark_before, (
            f"stage-4 failure advanced the watermark: before={watermark_before} "
            f"after={watermark_after} (stage 4 may only write max_id on success)"
        )

        # Replay: unpatched rerun processes the movement again and its day
        # lands in fact_movement_daily.
        replay = etl_database(force=False)
        assert replay["skipped"] is False, (
            "replay run was skipped - the movement must still be pending"
        )

        with get_cursor() as cur:
            cur.execute(
                "SELECT created_at::date AS day FROM movements "
                "WHERE reference = %s",
                ("TEST-T1B-STAGE4",),
            )
            day = cur.fetchone()["day"]
            cur.execute(
                "SELECT COUNT(*) AS c FROM fact_movement_daily "
                "WHERE date_key = %s",
                (day,),
            )
            fact_rows = cur.fetchone()["c"]

        assert fact_rows >= 1, (
            f"replayed movement day {day} missing from fact_movement_daily "
            f"(rows={fact_rows}) - stage-4 failure must not strand the movement"
        )
