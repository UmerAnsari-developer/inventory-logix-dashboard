"""RED-phase tests for Issue 02 — authentication service race condition.

Pins the code-reviewer findings on ``app/services/auth_service.py``
(``AuthService.authenticate``, ~L59-97):

* TOCTOU: the lockout gate (L69-75), the failure append (L78-79) and the
  success clear (L85-86) sit in SEPARATE critical sections with bcrypt
  ``verify_password`` in between — concurrent attempts all pass the gate
  before any append lands (spec scenarios 1/3 unmitigated).
* The lockout trigger at L75 writes NO audit row and NO log.
* ``datetime.utcnow()`` at L68/74/79/131/168 — needs a ``_utcnow()`` clock
  seam (Finding 3) so expiry is testable (and 3.14-clean).

TESTS ONLY — no implementation edits; backend-lead implements next.
Existing suites (tests/test_auth.py, tests/test_security.py) untouched.

Expected status BEFORE the fix:
  test_threshold_lockout_sequential          GREEN (regression pin — the
                                              sequential path already works)
  test_concurrent_failures_never_exceed...   RED   (TOCTOU overshoot, 10>5)
  test_success_resets_failed_counter         GREEN (regression pin)
  test_lockout_expires_after_window          RED   (AttributeError: _utcnow
                                              seam does not exist yet —
                                              acceptable red per plan)
  test_lockout_writes_audit_and_warning      RED   (nothing written/logged
                                              at L75)
  test_failure_after_success_is_retained     GREEN (forced ordering cannot
                                              expose the TOCTOU; regression
                                              pin for clear/append contract)
  test_login_post_requires_csrf_token        GREEN (cheap pin under a local
                                              WTF_CSRF_ENABLED override)
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

import app.services.auth_service as auth_mod
from app.database import get_cursor
from app.extensions import limiter
from app.repositories import UserRepository
from app.services.auth_service import (
    AuthError,
    AuthService,
    LOCKOUT_MINUTES,
    MAX_FAILED_ATTEMPTS,
)

PASSWORD = "LockoutTest1"
WRONG_PASSWORD = "WrongPassword1"
LOCK_LOGGER = "app.services.auth_service"


# ── Shared helpers / fixtures ────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_failed_logins():
    """Module-level lockout state must never bleed between tests."""
    auth_mod._failed_logins.clear()
    yield
    auth_mod._failed_logins.clear()


def _create_user(app, prefix: str) -> tuple[str, int]:
    """Fresh, uniquely-named user so counter state starts empty every run."""
    username = f"{prefix}_{uuid4().hex[:12]}"
    with app.app_context():
        uid = AuthService.register(username, f"{username}@example.com", PASSWORD)
    return username, uid


def _authenticate(app, username: str, password: str, ip: str = "127.0.0.1"):
    """Call authenticate inside a request context (login_user needs a session)."""
    with app.test_request_context("/auth/login", method="POST"):
        return AuthService.authenticate(username, password, ip=ip)


def _fail(app, username: str, ip: str = "127.0.0.1") -> None:
    """One wrong-password attempt that must fail as a normal (not locked) rejection."""
    with pytest.raises(AuthError, match="Invalid username or password"):
        _authenticate(app, username, WRONG_PASSWORD, ip=ip)


def _recorded_attempts(uid: int) -> int:
    entries = auth_mod._failed_logins.get(uid)
    return len(entries) if entries else 0


# ── 1. Threshold lockout, sequential (regression pin, GREEN today) ──────────

def test_threshold_lockout_sequential(app):
    """5 wrong passwords → the 6th attempt with the CORRECT password is locked.

    The sequential path already works today: keep as a regression pin so the
    concurrency fix cannot change threshold semantics.
    """
    username, uid = _create_user(app, "seq")

    for _ in range(MAX_FAILED_ATTEMPTS):
        _fail(app, username)
    assert _recorded_attempts(uid) == MAX_FAILED_ATTEMPTS

    with pytest.raises(AuthError, match="Account locked"):
        _authenticate(app, username, PASSWORD)  # CORRECT password, still locked


# ── 2. Concurrent failed logins — THE race proof (RED today) ────────────────

def test_concurrent_failures_never_exceed_threshold(app, monkeypatch):
    """Spec scenarios 1/3: N concurrent wrong-password calls, one fresh user.

    POST-FIX INVARIANT (asserted here):
      After all N=10 concurrent ``authenticate()`` calls complete,
        (a) the number of entries recorded in ``_failed_logins[uid]`` is
            ``<= MAX_FAILED_ATTEMPTS`` (5), and
        (b) the number of ``UserRepository.verify_password`` invocations
            admitted is ``<= MAX_FAILED_ATTEMPTS`` (5).
      I.OWERSHOT = 0: once the threshold is reached, no further password
      verification is performed and no further failure is recorded.
      Expected post-fix values: exactly 5 recorded / 5 verifies; the other
      5 calls raise "Account locked" at the gate WITHOUT invoking verify.

    RED today: gate (L69-75) and append (L78-79) are separate critical
    sections, so in-flight threads all pass the gate before any append —
    all 10 verify and all 10 append.

    The verify wrapper sleeps 50 ms so every thread reaches the check
    before any append lands (widens the race window pre-fix); the asserted
    invariants are timing-independent post-fix (lock spans check→verify→
    append), so the test is not flaky once the fix lands.
    """
    username, uid = _create_user(app, "race")

    real_verify = UserRepository.verify_password  # underlying plain function
    verify_calls: list[str] = []
    count_lock = threading.Lock()

    def slow_verify(plain: str, stored: str) -> bool:
        with count_lock:
            verify_calls.append(plain)
        time.sleep(0.05)  # TOCTOU window: all threads hit the gate first (RED);
        # post-fix this sleep runs while holding the per-user lock → serializes.
        return real_verify(plain, stored)

    monkeypatch.setattr(
        UserRepository, "verify_password", staticmethod(slow_verify)
    )

    n = 10
    barrier = threading.Barrier(n)
    outcomes: list[str] = []

    def worker() -> None:
        with app.test_request_context("/auth/login", method="POST"):
            barrier.wait(timeout=15)
            try:
                AuthService.authenticate(username, WRONG_PASSWORD, ip="10.0.0.9")
                outcomes.append("SUCCESS")  # never acceptable for a wrong password
            except AuthError as exc:
                outcomes.append(str(exc))

    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(worker) for _ in range(n)]
        for fut in futures:
            fut.result(timeout=60)

    assert "SUCCESS" not in outcomes, f"a wrong-password call authenticated: {outcomes}"

    recorded = _recorded_attempts(uid)
    verifies = len(verify_calls)
    assert recorded <= MAX_FAILED_ATTEMPTS, (
        f"TOCTOU overshoot: {recorded} failed attempts recorded for one user "
        f"(threshold {MAX_FAILED_ATTEMPTS}) — gate and append are not atomic"
    )
    assert verifies <= MAX_FAILED_ATTEMPTS, (
        f"{verifies} password verifications admitted once lockout should have "
        f"engaged (threshold {MAX_FAILED_ATTEMPTS})"
    )


# ── 3. Success resets the counter (regression pin, GREEN today) ─────────────

def test_success_resets_failed_counter(app):
    """4 failures → 1 success (clears) → 5 more failures still allowed →
    the 6th attempt after reset locks.

    If the clear were lost, the counter would still hold 4 after the
    success and the 2nd post-reset failure would already lock the account —
    so asserting 5 clean "Invalid" rejections pins the reset hard.
    """
    username, uid = _create_user(app, "reset")

    for _ in range(4):
        _fail(app, username)
    assert _recorded_attempts(uid) == 4

    user = _authenticate(app, username, PASSWORD)  # success must clear
    assert user["username"] == username
    assert _recorded_attempts(uid) == 0, "successful login must clear failed attempts"

    for _ in range(MAX_FAILED_ATTEMPTS):  # fresh counter: 5 rejections allowed
        with pytest.raises(AuthError, match="Invalid username or password"):
            _authenticate(app, username, WRONG_PASSWORD)
    assert _recorded_attempts(uid) == MAX_FAILED_ATTEMPTS

    with pytest.raises(AuthError, match="Account locked"):  # 6th-after-reset
        _authenticate(app, username, WRONG_PASSWORD)


# ── 4. Lockout expiry via the _utcnow() clock seam (RED today) ──────────────

def test_lockout_expires_after_window(app, monkeypatch):
    """Finding 3 — lockout must lapse LOCKOUT_MINUTES after the first
    recorded failure and the counter must start fresh afterwards.

    RED today: ``monkeypatch.setattr(auth_mod, "_utcnow", ...)`` raises
    AttributeError because the helper does not exist yet. That is the
    ACCEPTABLE RED — backend-lead must add, in
    ``app/services/auth_service.py``:

        def _utcnow() -> datetime:
            ...  # single clock source, used at all 5 former utcnow sites

    and replace ``datetime.utcnow()`` at L68 (cutoff), L74 (remaining-minutes
    math), L79 (failure append), L131 (reset-token expiry),
    L168 (reset-token check) with ``_utcnow()``. This test monkeypatches
    ``app.services.auth_service._utcnow``; leaving ANY of the five sites on
    the real clock makes the mixed-clock behaviour fail this test.
    """
    t0 = datetime(2026, 6, 1, 12, 0, 0)
    clock = {"now": t0}
    username, uid = _create_user(app, "expiry")
    # Acceptable RED: AttributeError — module has no `_utcnow` yet.
    monkeypatch.setattr(auth_mod, "_utcnow", lambda: clock["now"])

    for _ in range(MAX_FAILED_ATTEMPTS):
        _fail(app, username)  # timestamps recorded at fake t0

    with pytest.raises(AuthError, match="Account locked"):
        _authenticate(app, username, PASSWORD)  # locked at t0

    clock["now"] = t0 + timedelta(minutes=LOCKOUT_MINUTES + 1)

    user = _authenticate(app, username, PASSWORD)  # window elapsed → allowed
    assert user["username"] == username
    assert _recorded_attempts(uid) == 0, "expiry path must leave a fresh counter"

    for _ in range(4):  # fresh counter, not still locked
        with pytest.raises(AuthError, match="Invalid username or password"):
            _authenticate(app, username, WRONG_PASSWORD)


# ── 5. Lockout event is audited + logged (RED today) ────────────────────────

def test_lockout_writes_audit_and_warning(app, caplog):
    """Finding: the lockout trigger at L75 writes NO audit row and NO log.

    CONTRACT pinned for backend-lead (write both BEFORE raising at L75):
      * audit row via AuditRepository.record(uid, "user.account_locked",
        target_type="user", target_id=uid, ip_address=ip) → a row in
        audit_log with action='user.account_locked' for this user;
      * LOGGER.warning(...) on logger 'app.services.auth_service' whose
        formatted message contains the username.
    """
    caplog.set_level(logging.WARNING, logger=LOCK_LOGGER)

    username, uid = _create_user(app, "lockaud")
    for _ in range(MAX_FAILED_ATTEMPTS):
        _fail(app, username)
    with pytest.raises(AuthError, match="Account locked"):
        _authenticate(app, username, PASSWORD)  # gate raise → must audit + log

    with app.app_context():
        with get_cursor() as cur:
            cur.execute(
                "SELECT id FROM audit_log WHERE user_id = %s AND action = %s",
                (uid, "user.account_locked"),
            )
            rows = cur.fetchall()
    assert rows, (
        "lockout gate must write an audit row "
        "(action='user.account_locked') — none found for this user"
    )

    lock_warnings = [
        rec
        for rec in caplog.records
        if rec.levelno >= logging.WARNING
        and rec.name == LOCK_LOGGER
        and username in rec.getMessage()
    ]
    assert lock_warnings, (
        f"lockout must emit a WARNING from {LOCK_LOGGER} naming {username!r}"
    )


# ── 6. Success-vs-failure interleave, spec scenario 4 (regression pin) ──────

def test_failure_after_success_is_retained(app):
    """Spec scenario 4 — asserted invariant (documented precisely):

    A failed ``authenticate()`` that COMPLETES AFTER a successful
    ``authenticate()`` on the same user must still be recorded once both
    are done: the success clears the 4 seeded failures, the later failure
    appends → ``_failed_logins[uid]`` must contain EXACTLY 1 entry. The
    success itself must succeed (no false lockout) and a subsequent correct
    password must still authenticate (count=1 < threshold), clearing to 0.

    Failures completing BEFORE the success may legitimately be cleared —
    that transition (4 → 0) is pinned separately by
    test_success_resets_failed_counter.

    Ordering is forced (both threads barrier-synced at launch; the failure
    thread invokes authenticate only after the success thread fully
    completes) because "completes after" is otherwise undecidable: a free
    interleaving admits both 0-entry and 1-entry outcomes in ANY correct
    implementation, which would be flaky. Coordination happens OUTSIDE
    authenticate() so it cannot deadlock against a fix that holds the
    per-user lock across check→verify→append.

    GREEN today (forced pop-then-append already serialises correctly);
    kept as a regression pin so the per-user-lock refactor cannot lose the
    update between clear and append.
    """
    username, uid = _create_user(app, "inter")
    for _ in range(4):
        _fail(app, username)
    assert _recorded_attempts(uid) == 4

    barrier = threading.Barrier(2)
    success_done = threading.Event()

    def run_success() -> None:
        with app.test_request_context("/auth/login", method="POST"):
            barrier.wait(timeout=10)
            AuthService.authenticate(username, PASSWORD, ip="127.0.0.1")
            success_done.set()

    def run_failure() -> None:
        with app.test_request_context("/auth/login", method="POST"):
            barrier.wait(timeout=10)
            assert success_done.wait(timeout=10), "success thread never completed"
            with pytest.raises(AuthError, match="Invalid username or password"):
                AuthService.authenticate(username, WRONG_PASSWORD, ip="127.0.0.2")

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_success = pool.submit(run_success)
        fut_failure = pool.submit(run_failure)
        fut_success.result(timeout=30)  # surface success-thread errors first
        fut_failure.result(timeout=30)

    recorded = _recorded_attempts(uid)
    assert recorded == 1, (
        "a failure completing AFTER a success must survive the clear "
        f"(expected exactly 1 recorded attempt, got {recorded})"
    )

    user = _authenticate(app, username, PASSWORD)  # not falsely locked
    assert user["username"] == username
    assert _recorded_attempts(uid) == 0


# ── 7. CSRF on login POST (cheap pin under a local override) ────────────────

def test_login_post_requires_csrf_token(app):
    """POST /auth/login without a CSRF token → 400.

    conftest/TestingConfig disable CSRF globally; override the config key
    locally inside this test (flask_wtf reads WTF_CSRF_ENABLED per request)
    and restore it — no global fixture is weakened.
    """
    previous = app.config["WTF_CSRF_ENABLED"]
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        resp = app.test_client().post(
            "/auth/login",
            data={"username": "admin", "password": "Admin@123"},
        )
        assert resp.status_code == 400, (
            f"tokenless login POST must be rejected with 400, got {resp.status_code}"
        )
    finally:
        app.config["WTF_CSRF_ENABLED"] = previous
