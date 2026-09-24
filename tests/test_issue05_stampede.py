"""RED-phase regression tests for Issue 05 (cache stampede / single-flight).

Every test targets a consolidated code-review finding (F1-F6) or a documented
test-gap (1-8) and is designed to FAIL against the current code for the right
reason. backend-lead implements the fixes; these tests then go green. Do NOT
weaken them to get a pass.

Gap -> test -> expected status against CURRENT code:

  1  test_t1_cold_key_single_flight             GREEN (regression guard:
     TTLCache already single-flights cold keys — keep it pinned)
  2  test_t2_expired_key_single_flight          GREEN (regression guard:
     expiry + per-key lock already de-duplicate the recompute)
  3  test_t3_reports_cache_key_not_busted       RED   (F2: reports key has
     no "reports:" prefix, so cache_bust_products() cannot drop it)
  4  test_t4_api_product_keys_not_busted        RED   (F2: make_key output
     and "product:<id>" never match invalidate("products"))
  5a test_t5a_dashboard_concurrent_cold_load    RED   (F1/F4: manual
     get/set lets every cold request run the query battery)
  5b test_t5b_dashboard_monitoring_check_once   RED   (F4 x F6: two cold
     loads spawn two run_monitoring_checks whose guard races)
  6  test_t6_forecast_portfolio_single_flight   RED   (F3: manual get/set
     around ForecastService.portfolio bypasses the lock)
  7  test_t7_rebuild_locks_stays_bounded        RED   (F5: _rebuild_locks
     grows forever — one Lock per key ever seen)
  8  test_t8_run_monitoring_checks_single_flight RED  (F6: check-then-act
     on notif_monitor_last lets both threads run the checks)

Fix-shape notes for backend-lead (tests 3-4):
  * T3 seeds the EXACT key the production /reports route builds today (raw
    make_key(date_from=..., ...)). It goes green if the fix invalidates
    reports_cache wholesale (invalidate("")) or if key construction gains a
    reports prefix — in the latter case UPDATE THIS TEST'S SEED to the new
    production key shape so it keeps testing the real call site.
  * T4 seeds make_key(prefix="products", page=1, per_page=20) and
    "product:42" exactly as api.py builds them. Same rule: keep the seed in
    lockstep with production key construction (e.g. if make_key is changed
    to emit the prefix first, or api.py switches to "products|"+make_key).

No existing test files are edited. tests/test_cache.py::test_bust_helpers
only seeds already-prefixed keys ("reports:summary" etc.) and stays green
under every fix shape above.

F4 constraint under test in T5b: the monitoring-check spawn must remain
OUTSIDE the get_or_set producer/lock, yet its side effect (the actual
checks) may fire at most once per concurrent cold burst — achievable via
the F6 single-flight on notif_monitor_last and/or spawning only from the
rebuilding thread.
"""
from __future__ import annotations

import threading
import time

import pytest

from app.utils.cache import TTLCache, api_cache, cache_bust_products, make_key, reports_cache


# ---------------------------------------------------------------------------
# fixtures — several tests seed the module-level cache singletons; T5/T8
# additionally depend on cold state for determinism. Clear before AND after.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_caches():
    from app.utils import cache as cache_mod
    import app.routes.ai as ai_mod

    caches = (
        cache_mod.products_cache,
        cache_mod.suppliers_cache,
        cache_mod.dashboard_cache,
        cache_mod.reports_cache,
        cache_mod.global_cache,
        cache_mod.api_cache,
        cache_mod.landing_cache,
        cache_mod.monitoring_cache,
        ai_mod._portfolio_cache,
    )
    for c in caches:
        c.clear()
    yield
    for c in caches:
        c.clear()


# ---------------------------------------------------------------------------
# helpers (patterns reused from the existing suites)
# ---------------------------------------------------------------------------

def _session_client(app, username: str):
    """Authenticated test client without hitting the /auth/login rate limiter.

    Sets the same Flask-Login session keys login_user() would, including the
    strong session-protection identifier. Copied from
    tests/test_frontend_mitigations.py::_session_client — each call returns a
    SEPARATE client so concurrent threads never share a cookie jar.
    """
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


def _install_dashboard_cursor_gate(monkeypatch, ui_module):
    """Hold the FIRST dashboard-builder get_cursor entry until released.

    Only entry #1 blocks: the requesting thread A stops at the builder door
    (before opening a DB connection) while the dashboard cache stays cold, so
    thread B is guaranteed to take the miss path. Under current code B then
    enters the builder too (entries == 2 -> RED); under a correct
    get_or_set single-flight B blocks on the per-key lock instead and never
    reaches get_cursor (entries == 1 -> GREEN).
    """
    entries: list[int] = []
    builder_started = threading.Event()
    release = threading.Event()
    orig_get_cursor = ui_module.get_cursor

    def gated_get_cursor(*args, **kwargs):
        entries.append(1)
        if len(entries) == 1:
            builder_started.set()
            if not release.wait(15):
                raise RuntimeError("dashboard builder gate never released")
        return orig_get_cursor(*args, **kwargs)

    monkeypatch.setattr(ui_module, "get_cursor", gated_get_cursor)
    return entries, builder_started, release


def _drive_concurrent_dashboard(app, entries, builder_started, release):
    """Fire two authenticated GET / requests with A gated inside the builder.

    Returns {"a": <status>, "b": <status>}. Always releases the gate in a
    finally block so a failing assertion can never leave thread A blocked
    (and pytest hung) at interpreter exit.
    """
    client_a = _session_client(app, "admin")
    client_b = _session_client(app, "admin")
    statuses: dict[str, object] = {}

    def _run(name, client):
        try:
            statuses[name] = client.get("/").status_code
        except Exception as exc:  # surface route crashes instead of KeyError
            statuses[name] = f"EXC:{exc!r}"

    ta = threading.Thread(target=_run, args=("a", client_a))
    ta.start()
    tb = None
    try:
        if not builder_started.wait(15):
            raise AssertionError("thread A never reached the dashboard builder")
        tb = threading.Thread(target=_run, args=("b", client_b))
        tb.start()
        # Wait until B also enters the builder (current code: no single
        # flight). Under a correct fix B blocks on the cache lock and this
        # loop simply times out — that timeout is the GREEN path.
        deadline = time.time() + 1.5
        while time.time() < deadline and len(entries) < 2:
            time.sleep(0.02)
    finally:
        release.set()
        ta.join(30)
        if tb is not None:
            tb.join(30)

    assert not ta.is_alive(), "dashboard request thread A hung"
    assert tb is not None and not tb.is_alive(), "dashboard request thread B hung"
    assert len(statuses) == 2, f"requests incomplete: {statuses}"
    return statuses


def _force_notif_guard_race(monkeypatch, global_cache, key="notif_monitor_last", wait_s=5.0):
    """Widen run_monitoring_checks' check-then-act window (F6) deterministically.

    The FIRST guard read on `key` is held open until a second read happens,
    then returns a forced miss (None) unconditionally — so under current code
    BOTH racing threads pass the `last_run is not None` guard and run the
    checks. The second reader performs its real read BEFORE unblocking the
    first, so the marker can never be observed by reader #2.

    After the F6 fix (global_cache.get_or_set single-flight) only one thread
    produces: the second reader sees the sentinel, wins the key lock, runs
    the checks once; the first thread then reads the forced None from
    get_or_set's initial probe and returns without producing.

    Non-matching keys (e.g. "settings:<id>" from SettingsService) pass
    straight through to the real get.
    """
    real_get = global_cache.get
    second_read = threading.Event()
    n = {"count": 0}

    def gated_get(k, *args, **kwargs):
        if k != key:
            return real_get(k, *args, **kwargs)
        n["count"] += 1
        if n["count"] == 1:
            second_read.wait(wait_s)
            return None  # forced miss — widen the race window
        if n["count"] == 2:
            result = real_get(k, *args, **kwargs)  # read BEFORE unblocking #1
            second_read.set()
            return result
        return real_get(k, *args, **kwargs)

    monkeypatch.setattr(global_cache, "get", gated_get)


def _await_check_stability(stats, early_exit=2, timeout=4.0, stable_for=0.7):
    """Poll the check counters until they stop moving (or hit `early_exit`).

    The dashboard's monitoring check runs on fire-and-forget daemon threads,
    so an exact post-join read is racy; bounded polling keeps the assertion
    deterministic. `early_exit == 2` returns the moment duplicate runs are
    proven — the RED path exits fast.
    """
    deadline = time.time() + timeout
    last = len(stats["stale"])
    since = time.time()
    while time.time() < deadline:
        cur = len(stats["stale"])
        if cur >= early_exit:
            return
        if cur != last:
            last, since = cur, time.time()
        elif time.time() - since >= stable_for:
            return
        time.sleep(0.02)


def _await_rmc_quiescence(stats, timeout=8.0, stable_for=1.0):
    """Wait until every started run_monitoring_checks invocation has finished.

    Called BEFORE the failing assertion so a RED run still drains its
    fire-and-forget threads while the monkeypatches are installed (a thread
    resuming after teardown would otherwise execute the real DB checks).
    """
    deadline = time.time() + timeout
    stable_since = time.time()
    while time.time() < deadline:
        started = len(stats["started"])
        if started >= 1 and len(stats["done"]) >= started:
            if time.time() - stable_since >= stable_for:
                return
        else:
            stable_since = time.time()
        time.sleep(0.05)


# ---------------------------------------------------------------------------
# T1 - gap 1: cold-key single-flight (regression guard — expected GREEN)
# ---------------------------------------------------------------------------

def test_t1_cold_key_single_flight():
    """N threads hit one cold key while the producer sleeps on a gate →
    the producer must run exactly once and every thread gets its value."""
    c = TTLCache(ttl=60, max_entries=10)
    calls: list[int] = []
    first_inside = threading.Event()
    release = threading.Event()
    results: list = []
    errors: list = []

    def producer():
        calls.append(1)
        first_inside.set()
        assert release.wait(10), "producer gate never released"
        return {"v": 42}

    def worker():
        try:
            results.append(c.get_or_set("cold-key", producer))
        except Exception as exc:  # noqa: BLE001 — collected for the assert
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    assert first_inside.wait(10), "no thread reached the producer"
    time.sleep(0.2)  # let the rest of the herd pile up on the per-key lock
    release.set()
    for t in threads:
        t.join(10)

    assert not any(t.is_alive() for t in threads), "worker thread hung"
    assert not errors, f"worker exceptions: {errors}"
    assert len(calls) == 1, f"producer ran {len(calls)}x on a cold key (single-flight broken)"
    assert len(results) == 8, f"only {len(results)}/8 threads got a result"
    assert all(r == {"v": 42} for r in results), f"mixed results: {results}"


# ---------------------------------------------------------------------------
# T2 - gap 2: single-flight across TTL expiry (regression guard — GREEN)
# ---------------------------------------------------------------------------

def test_t2_expired_key_single_flight():
    """Seed → expire → thread A recomputes slowly; thread B joins mid-flight.
    The expired entry must not allow a second producer run (call count == 1)."""
    c = TTLCache(ttl=0.05, max_entries=10)
    c.set("k", "stale")
    time.sleep(0.06)  # entry is now expired
    assert c.get("k") is None, "seeded entry should have expired"

    calls: list[str] = []
    a_inside = threading.Event()
    release = threading.Event()
    results: list = []

    def slow_refresh():
        calls.append("A")
        a_inside.set()
        assert release.wait(10), "recompute gate never released"
        return "fresh"

    def b_producer():
        calls.append("B")
        return "B-SHOULD-NOT-RUN"

    def thread_a():
        results.append(c.get_or_set("k", slow_refresh))

    def thread_b():
        assert a_inside.wait(10), "thread A never started its recompute"
        results.append(c.get_or_set("k", b_producer))

    ta = threading.Thread(target=thread_a)
    tb = threading.Thread(target=thread_b)
    ta.start()
    tb.start()
    assert a_inside.wait(10), "thread A never reached its producer"
    time.sleep(0.2)  # B piles up on the per-key lock while A recomputes
    release.set()
    ta.join(10)
    tb.join(10)

    assert not ta.is_alive() and not tb.is_alive(), "worker thread hung"
    assert calls == ["A"], f"expected exactly one producer run, got {calls}"
    assert len(results) == 2 and all(r == "fresh" for r in results), (
        f"both threads must observe the single recomputed value, got {results}"
    )


# ---------------------------------------------------------------------------
# T3 - F2 HIGH (gap 3): reports key is invisible to cache_bust_products
# ---------------------------------------------------------------------------

def test_t3_reports_cache_key_not_busted():
    """F2: the /reports route builds its key with raw make_key(date_from=...,
    date_to=..., warehouses=..., categories=...) — no reports: prefix — while
    cache_bust_products() only drops reports_cache keys matching "reports:".
    So a product write leaves the 2-hour reports entry in place (stale data).

    Seed the REAL production key shape; after the bust it must be gone.
    """
    key = make_key(
        date_from="2026-01-01",
        date_to="2026-01-31",
        warehouses="WH-01",
        categories="Electronics",
    )
    # Sanity: proves we seeded exactly what make_key produces (falsy-skip +
    # alphabetical order), so a failure below is about invalidation, not key
    # construction drifting apart from the test.
    payload = {"kpis": {"total_units": 123}}
    reports_cache.set(key, payload)
    assert reports_cache.get(key) == payload, "seeded reports key not readable"

    cache_bust_products()

    assert reports_cache.get(key) is None, (
        f"reports key {key!r} survived cache_bust_products() — it lacks the "
        f"reports: prefix that invalidate() matches, so report data stays "
        f"stale for up to 2h after a product write (F2)"
    )


# ---------------------------------------------------------------------------
# T4 - F2 HIGH (gap 4): api product list + detail keys invisible to bust
# ---------------------------------------------------------------------------

def test_t4_api_product_keys_not_busted():
    """F2: api.py builds list keys as make_key(prefix="products", page=...,
    per_page=...) — sorted alphabetically, so the key STARTS with "page=" —
    and detail keys as "product:<id>". cache_bust_products() invalidates the
    "products" prefix, which matches NEITHER ("product:42" starts with
    "product:", not "products"). Both must be dropped by the bust.
    """
    list_key = make_key(prefix="products", page=1, per_page=20)
    detail_key = "product:42"

    api_cache.set(list_key, {"rows": [], "pagination": {"page": 1}})
    api_cache.set(detail_key, {"id": 42, "sku": "SKU-42"})
    assert api_cache.get(list_key) is not None
    assert api_cache.get(detail_key) is not None

    cache_bust_products()

    assert api_cache.get(list_key) is None, (
        f"api list key {list_key!r} survived cache_bust_products() — "
        f"make_key output never starts with the 'products' prefix (F2)"
    )
    assert api_cache.get(detail_key) is None, (
        f"api detail key {detail_key!r} survived cache_bust_products() — "
        f"'product:<id>' does not match invalidate('products') (F2)"
    )


# ---------------------------------------------------------------------------
# T5a - F1/F4 MED (gap 5): dashboard builder must single-flight
# ---------------------------------------------------------------------------

def test_t5a_dashboard_concurrent_cold_load(app, monkeypatch):
    """F1/F4: two concurrent cold GET / must run the (expensive) dashboard
    query battery exactly once. Current code does manual get + set with no
    lock, so both requests build → entries == 2.

    Gate design: thread A stops at the builder door (before any DB work) with
    the cache still cold; B is then guaranteed to take the miss path. Also
    stubs run_monitoring_checks so fire-and-forget threads from this test
    cannot leak real DB side effects into other tests.
    """
    import app.routes.ui as ui_module
    import app.services.notification_service as ns

    monkeypatch.setattr(ns, "run_monitoring_checks", lambda: {"skipped": True})

    entries, builder_started, release = _install_dashboard_cursor_gate(
        monkeypatch, ui_module
    )
    statuses = _drive_concurrent_dashboard(app, entries, builder_started, release)

    assert statuses == {"a": 200, "b": 200}, f"unexpected responses: {statuses}"
    assert len(entries) == 1, (
        f"dashboard builder started {len(entries)} times under concurrent "
        f"cold loads (expected 1) — convert dashboard get/set to "
        f"dashboard_cache.get_or_set (F1/F4)"
    )


# ---------------------------------------------------------------------------
# T5b - F4 x F6 (gap 5): monitoring-check side effect at most once
# ---------------------------------------------------------------------------

def test_t5b_dashboard_monitoring_check_once(app, monkeypatch):
    """F4 x F6: concurrent cold dashboard loads must trigger the monitoring
    checks (clear_stale / reorder / out-of-stock) at most ONCE in total.

    Current code spawns run_monitoring_checks on EVERY cache miss (two
    threads → two spawns) and run_monitoring_checks' check-then-act guard on
    notif_monitor_last lets both through — _force_notif_guard_race makes that
    race deterministic instead of timing-dependent. GREEN requires the F6
    single-flight (and/or spawning only from the rebuilding thread); the
    spawn itself must stay OUTSIDE the get_or_set producer (F4 constraint).

    Counters are plain lists (atomic append) — `+=` on shared ints can lose
    updates under exactly the concurrency we are testing.
    """
    import app.routes.ui as ui_module
    import app.services.notification_service as ns

    stats: dict[str, list] = {
        "started": [], "done": [], "stale": [], "reorder": [], "out": [],
    }

    real_rmc = ns.run_monitoring_checks

    def counting_rmc():
        stats["started"].append(1)
        try:
            return real_rmc()
        finally:
            stats["done"].append(1)

    def stub(name):
        def _s(*args, **kwargs):
            stats[name].append(1)
            return 0
        return _s

    monkeypatch.setattr(ns, "run_monitoring_checks", counting_rmc)
    monkeypatch.setattr(ns, "clear_stale_notifications", stub("stale"))
    monkeypatch.setattr(ns, "check_reorder_alerts", stub("reorder"))
    monkeypatch.setattr(ns, "check_out_of_stock", stub("out"))
    _force_notif_guard_race(monkeypatch, ns.global_cache)

    entries, builder_started, release = _install_dashboard_cursor_gate(
        monkeypatch, ui_module
    )
    statuses = _drive_concurrent_dashboard(app, entries, builder_started, release)
    assert statuses == {"a": 200, "b": 200}, f"unexpected responses: {statuses}"
    # Orchestrator adjudication: RED-phase harness check here wrongly pinned
    # PRE-fix behaviour (entries==2) and contradicted T5a's entries==1 on the
    # same gate plus the F4 spec (B blocks at the per-key lock, never enters
    # the builder). Corrected to the post-fix invariant; the real behavioural
    # guard remains the checks<=1 assertion below.
    assert len(entries) == 1, (
        f"dashboard builder started {len(entries)} times under concurrent "
        f"cold loads (expected 1) — B must block at the per-key lock (F4)"
    )

    _await_check_stability(stats)
    _await_rmc_quiescence(stats)  # drain BEFORE asserting so a RED failure
    # still leaves no fire-and-forget thread running against restored patches

    assert len(stats["stale"]) <= 1 and len(stats["reorder"]) <= 1 and len(stats["out"]) <= 1, (
        f"monitoring checks ran more than once across concurrent cold "
        f"dashboard loads: stale={len(stats['stale'])} "
        f"reorder={len(stats['reorder'])} out={len(stats['out'])} "
        f"(started={len(stats['started'])}) — single-flight "
        f"notif_monitor_last via global_cache.get_or_set (F6) and/or spawn "
        f"only from the rebuilding thread (F4)"
    )


# ---------------------------------------------------------------------------
# T6 - F3 HIGH (gap 6): forecast portfolio bypasses the per-key lock
# ---------------------------------------------------------------------------

def test_t6_forecast_portfolio_single_flight(app, monkeypatch):
    """F3: /ai/forecast/portfolio does manual get/set around
    ForecastService.portfolio (Prophet/ARIMA fitting) instead of
    _portfolio_cache.get_or_set, so two concurrent cold calls both fit.
    Mock the fit, clear the cache, fire two requests while the first fit is
    gated — the mock must be called exactly once.
    """
    import app.routes.ai as ai_mod

    ai_mod._portfolio_cache.clear()

    calls: list[int] = []
    first_inside = threading.Event()
    release = threading.Event()

    def fake_portfolio(horizon: int = 30, model: str = "prophet"):
        calls.append(1)
        first_inside.set()
        assert release.wait(10), "portfolio gate never released"
        return [{"sku": "SKU-1", "forecast_total": 5}]

    monkeypatch.setattr(ai_mod.ForecastService, "portfolio", fake_portfolio)

    client_a = _session_client(app, "admin")
    client_b = _session_client(app, "admin")
    statuses: dict[str, object] = {}
    url = "/ai/forecast/portfolio?horizon=31&model=prophet"

    def _run(name, client):
        try:
            statuses[name] = client.get(url).status_code
        except Exception as exc:  # noqa: BLE001
            statuses[name] = f"EXC:{exc!r}"

    ta = threading.Thread(target=_run, args=("a", client_a))
    ta.start()
    assert first_inside.wait(10), "thread A never reached the portfolio fit"
    tb = threading.Thread(target=_run, args=("b", client_b))
    tb.start()
    try:
        # RED path: B reaches the (unguarded) fit while A is gated → calls
        # hits 2 and the loop exits fast. GREEN path: B blocks on the
        # per-key lock, the loop times out, then the gate releases.
        deadline = time.time() + 1.0
        while time.time() < deadline and len(calls) < 2:
            time.sleep(0.02)
    finally:
        release.set()
        ta.join(15)
        tb.join(15)

    assert not ta.is_alive() and not tb.is_alive(), "portfolio request thread hung"
    assert statuses == {"a": 200, "b": 200}, f"unexpected responses: {statuses}"
    assert len(calls) == 1, (
        f"ForecastService.portfolio ran {len(calls)}x under concurrent cold "
        f"requests (expected 1) — convert manual get/set to "
        f"_portfolio_cache.get_or_set (F3)"
    )


# ---------------------------------------------------------------------------
# T7 - F5 MED (gap 7): _rebuild_locks must be bounded (WeakValueDictionary)
# ---------------------------------------------------------------------------

def test_t7_rebuild_locks_stays_bounded():
    """F5: every distinct key ever passed to get_or_set permanently registers
    a Lock in the plain dict `_rebuild_locks`. After touching 10k distinct
    keys and dropping all references, the mapping must be ~empty (fixed via
    weakref.WeakValueDictionary); today it holds all 10k entries.
    """
    c = TTLCache(ttl=60, max_entries=10)

    for i in range(10_000):
        c.get_or_set(f"key{i}", lambda i=i: i)
    # No live references to any per-key lock remain at this point — every
    # get_or_set call has returned and its local `key_lock` went out of scope.

    remaining = len(c._rebuild_locks)
    assert remaining <= 10, (
        f"_rebuild_locks kept {remaining} per-key locks after 10k distinct "
        f"get_or_set keys with no live references — unbounded growth (F5: "
        f"store locks in weakref.WeakValueDictionary)"
    )


# ---------------------------------------------------------------------------
# T8 - F6 MED (gap 8): run_monitoring_checks check-then-act race
# ---------------------------------------------------------------------------

def test_t8_run_monitoring_checks_single_flight(monkeypatch):
    """F6: two threads call run_monitoring_checks concurrently on a cold
    global_cache. The guard is check-then-act (get → None → set → run), so
    both pass today. _force_notif_guard_race makes the interleave
    deterministic; each mocked check must run at most once in total.

    GREEN requires routing the body through
    global_cache.get_or_set("notif_monitor_last", _run_checks).
    """
    import app.services.notification_service as ns

    stats: dict[str, list] = {"stale": [], "reorder": [], "out": []}

    def stub(name):
        def _s(*args, **kwargs):
            stats[name].append(1)
            return 0
        return _s

    monkeypatch.setattr(ns, "clear_stale_notifications", stub("stale"))
    monkeypatch.setattr(ns, "check_reorder_alerts", stub("reorder"))
    monkeypatch.setattr(ns, "check_out_of_stock", stub("out"))
    _force_notif_guard_race(monkeypatch, ns.global_cache)

    errors: list = []

    def worker():
        try:
            ns.run_monitoring_checks()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join(15)
    t2.join(15)

    assert not t1.is_alive() and not t2.is_alive(), "run_monitoring_checks thread hung"
    assert not errors, f"worker exceptions: {errors}"
    assert len(stats["stale"]) <= 1 and len(stats["reorder"]) <= 1 and len(stats["out"]) <= 1, (
        f"checks ran twice under a forced guard race: stale={len(stats['stale'])} "
        f"reorder={len(stats['reorder'])} out={len(stats['out'])} — "
        f"check-then-act on notif_monitor_last must become "
        f"global_cache.get_or_set single-flight (F6)"
    )
