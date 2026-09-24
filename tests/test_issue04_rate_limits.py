"""RED-phase tests for Issue 04 — rate limiting (flask-limiter) hardening.

Every test pins a consolidated code-review finding (#1-#9) or the review's
test-gap list, written against the APPROVED first-pass review contract:

* Redis / shared limiter store is DEFERRED (1 worker x 1 instance pinned on
  the Render free tier). No test requires Redis; memory:// must keep working.
  Revisit trigger: ``workers>1 or instances>1`` (finding #4 — untested by
  design, nothing here talks to a remote store).
* Finding #1 trust model: opt-in ``TRUST_PROXY`` env/config, default OFF.
  When truthy the app installs ``ProxyFix(x_for=1, x_proto=1)`` (or an
  equivalent X-Forwarded-For aware key_func) so flask-limiter keys on the
  forwarded client hop; default OFF keeps XFF spoof-proof on direct exposure.
  BOTH sides are pinned (untrusted + trusted tests).
* Finding #9 (decorator order on run-etl: @limiter.limit vs
  @login_required/@write_roles_required) is cosmetic — intentionally
  untested; the limit test only pins observable 429 behaviour.

Gap/finding -> test -> expected status against CURRENT code:

  existing   test_login_429_after_10_bad_attempts  GREEN (10/min on
     POST /auth/login already exists; also pins finding #7's NON-api side:
     a page-route 429 must stay text/html after the JSON fix lands for
     /api/* only)
  existing   test_register_429_after_5             GREEN (5/min exists;
     invalid email fails validate_email pre-DB, so no account is created)
  existing   test_products_post_429_after_30       GREEN (30/min on
     POST /api/products exists; json={} fails validate_payload pre-insert)
  existing   test_movements_post_429_after_60      GREEN (60/min exists;
     json={} raises MovementError("Product is required.") pre-DB)
  existing   test_limits_keyed_per_remote_addr     GREEN (key_func =
     get_remote_address already isolates buckets per REMOTE_ADDR)
  #1         test_xff_ignored_when_trust_proxy_off GREEN-as-pin (XFF is
     ignored today; MUST STAY green post-fix with TRUST_PROXY off — a
     spoofed/rotating XFF must never reset an untrusted bucket)
  #1         test_xff_trusted_when_trust_proxy_on  RED (no ProxyFix /
     TRUST_PROXY wiring exists anywhere in the repo: the request carrying
     a DIFFERENT X-Forwarded-For client still hits the exhausted
     REMOTE_ADDR bucket — 429 instead of 401)
  #2         test_portfolio_endpoints_429_after_6  RED x2 (no explicit
     limit on /ai/forecast/portfolio or /ai/anomaly/portfolio; default
     200/min never trips at 7 — fix must add 6 per minute)
  #3         test_run_etl_429_after_5              RED (no explicit limit
     on POST /monitoring/run-etl; fix = 5 per minute. etl_database is
     monkeypatched to a no-op BEFORE posting, so no real ETL runs; Issue
     06's in-flight lock, when implemented, cannot mask the 429 because
     flask-limiter counts in before_request, BEFORE the view body)
  #7         test_api_429_is_json_envelope         RED (the shared
     errorhandler(429) always renders templates/errors/429.html — /api/*
     must return the JSON envelope {success: false, error: {...}})
  #5         test_ratelimit_storage_uri_wired      RED (RATELIMIT_STORAGE_URI
     is fully shadowed: settings.py defines no such Config attribute and
     extensions.py hardcodes storage_uri="memory://" on the constructor,
     which wins over flask-limiter's config lookup in init_app)
  #6         test_settings_put_429_after_30        RED (PUT /api/settings
     has no explicit limit — non-blocking parity fix: 30 per minute,
     matching the other API writes)

Do NOT weaken these to get a pass. backend-lead implements #1, #2, #3, #5,
#6 and #7 — implementation REQUIRED for GREEN (#4 stays deferred; #9 needs
no test).

Residual for backend-lead (#5): beyond the Config wiring these tests can
observe, the constructor kwarg ``storage_uri="memory://"`` in
app/extensions.py must be removed too — flask-limiter's init_app prefers
``self._storage_uri`` over config, so the kwarg would keep shadowing the
Config value even after Config gains the attribute. That residual cannot be
behaviourally asserted with memory:// as the default, hence it is documented
here rather than tested.

Hygiene: tests/conftest.py carries a suite-wide autouse
``_reset_rate_limiter`` fixture (the app — and its limiter — are
session-scoped, so buckets would otherwise leak between tests); it replaces
the ad-hoc ``limiter.reset()`` calls removed from test_auth_lockout.py and
test_frontend_mitigations.py.
"""
from __future__ import annotations

import importlib

import pytest

from app.services import AnomalyService, ForecastService

# Bad-credential POST body: the username does not exist, so
# AuthService.authenticate raises at the find_by_username miss — no failed
# attempt is recorded, no lockout is armed, and `admin` can never be locked
# out from here (the conftest auth_client fixture depends on admin).
_BAD_CREDS = {"username": "issue04_ghost", "password": "WrongPass1"}

_REGISTER_BAD = {
    "username": "issue04_newbie",
    "email": "not-an-email",  # fails validate_email before any DB write
    "password": "x",
}


# ---------------------------------------------------------------------------
# helpers (patterns reused from the existing suites)
# ---------------------------------------------------------------------------

def _session_client(app, username: str):
    """Authenticated test client without hitting the /auth/login rate limiter.

    Sets the same Flask-Login session keys login_user() would, including the
    strong session-protection identifier. Copied from
    tests/test_issue05_stampede.py::_session_client — each call returns a
    SEPARATE client so a burst never shares state accidentally.
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


def _stub_portfolio(**_kwargs):
    """Stand-in for ForecastService.portfolio / AnomalyService.portfolio.

    The views cache the result, so this runs at most once per cache key and
    no model fitting ever happens in a rate-limit test.
    """
    return [{"sku": "STUB", "stub": True}]


# ---------------------------------------------------------------------------
# existing limits — GREEN regression guards (pin the shipped thresholds so
# a refactor of extensions.py cannot silently drop them)
# ---------------------------------------------------------------------------

def test_login_429_after_10_bad_attempts(app):
    """11 bad-cred POSTs /auth/login -> [401]*10 then 429 (10/min exists).

    Also pins finding #7's NON-api side: the 429 for a page route must stay
    text/html (template error page / no-DB fallback) once the JSON envelope
    is added for /api/* routes only.
    """
    client = app.test_client()
    responses = [client.post("/auth/login", data=_BAD_CREDS) for _ in range(11)]
    statuses = [r.status_code for r in responses]
    assert statuses == [401] * 10 + [429], f"unexpected login statuses: {statuses}"
    last = responses[10]
    assert last.content_type and last.content_type.startswith("text/html"), (
        "non-API 429 must stay the HTML error page (finding #7 requires JSON "
        f"for /api/* ONLY), got content-type {last.content_type!r}"
    )


def test_register_429_after_5(app):
    """6 invalid POSTs /auth/register -> [400]*5 then 429 (5/min exists).

    The broken email fails validate_email inside AuthService.register before
    any DB write, so no account can be created by this burst.
    """
    client = app.test_client()
    responses = [client.post("/auth/register", data=_REGISTER_BAD) for _ in range(6)]
    statuses = [r.status_code for r in responses]
    assert statuses == [400] * 5 + [429], (
        "5 per minute on POST /auth/register: five validation rejections "
        f"then 429 on the 6th, got {statuses}"
    )


def test_products_post_429_after_30(app):
    """31 POSTs /api/products (json={}) -> 31st is 429 (30/min exists).

    json={} fails ProductService.validate_payload before any insert, so the
    burst is pure validation overhead — cheap and side-effect free.
    """
    client = _session_client(app, "admin")
    responses = [client.post("/api/products", json={}) for _ in range(31)]
    statuses = [r.status_code for r in responses]
    assert all(s in (400, 422) for s in statuses[:30]), (
        f"invalid payload must be rejected pre-insert: {statuses[:30]}"
    )
    assert statuses[30] == 429, (
        f"31st POST /api/products must hit the 30/min limit, got {statuses[30]}"
    )


def test_movements_post_429_after_60(app):
    """61 POSTs /api/movements (json={}) -> 61st is 429 (60/min exists).

    json={} makes MovementService.record raise MovementError("Product is
    required.") before any DB write — the loop stays validation-only.
    """
    client = _session_client(app, "admin")
    responses = [client.post("/api/movements", json={}) for _ in range(61)]
    statuses = [r.status_code for r in responses]
    assert all(s in (400, 422) for s in statuses[:60]), (
        f"invalid payload must be rejected pre-insert: {statuses[:60]}"
    )
    assert statuses[60] == 429, (
        f"61st POST /api/movements must hit the 60/min limit, got {statuses[60]}"
    )


# ---------------------------------------------------------------------------
# #1 — proxy-aware keying: BOTH trust states pinned
# ---------------------------------------------------------------------------

def test_limits_keyed_per_remote_addr(app):
    """Baseline for finding #1: buckets are keyed per REMOTE_ADDR today.

    11 bad-cred POSTs from 10.0.0.1 exhaust at exactly the 11th request;
    a different REMOTE_ADDR immediately gets its own bucket (401, not 429).
    This must hold under every accepted #1 fix shape.
    """
    client = app.test_client()
    a = [
        client.post(
            "/auth/login",
            data=_BAD_CREDS,
            environ_base={"REMOTE_ADDR": "10.0.0.1"},
        ).status_code
        for _ in range(11)
    ]
    assert a == [401] * 10 + [429], f"10.0.0.1 bucket wrong: {a}"
    b = client.post(
        "/auth/login",
        data=_BAD_CREDS,
        environ_base={"REMOTE_ADDR": "10.0.0.2"},
    ).status_code
    assert b == 401, (
        "a different REMOTE_ADDR must get its own bucket (key_func = "
        f"get_remote_address); 10.0.0.2 got {b}"
    )


def test_xff_ignored_when_trust_proxy_off(app):
    """#1 untrusted side — GREEN-as-pin: must stay green after the fix.

    TRUST_PROXY defaults OFF, so a spoofed/ROTATING X-Forwarded-For must
    never reset the bucket: all 11 requests key on the same REMOTE_ADDR and
    the 11th is 429. This flips RED if a fix ever trusts XFF by default.
    """
    client = app.test_client()
    statuses = [
        client.post(
            "/auth/login",
            data=_BAD_CREDS,
            environ_base={"REMOTE_ADDR": "10.0.0.9"},
            headers={"X-Forwarded-For": f"198.51.100.{i}"},
        ).status_code
        for i in range(11)
    ]
    assert statuses == [401] * 10 + [429], (
        "spoofed X-Forwarded-For must NOT reset the untrusted bucket "
        f"(TRUST_PROXY is off by default), got {statuses}"
    )


def test_xff_trusted_when_trust_proxy_on(monkeypatch):
    """#1 RED: with TRUST_PROXY=1 the key must follow the XFF first hop.

    Accepts both impl shapes: TRUST_PROXY read into Config at class-body
    time (hence the settings reload) OR read from os.environ inside
    create_app/key_func (hence setenv, still active for the whole test).
    Current code has no ProxyFix/TRUST_PROXY anywhere: every request keys on
    REMOTE_ADDR, so the request carrying a DIFFERENT forwarded client still
    hits the exhausted bucket — 429 instead of 401 (the RED trigger below).
    finally restores env AND reimports pristine Config classes so the
    session app and later tests are unaffected.
    """
    import app.config.settings as settings_mod
    from app import create_app
    from app.extensions import limiter

    monkeypatch.setenv("TRUST_PROXY", "1")
    importlib.reload(settings_mod)
    try:
        fresh = create_app("testing")
        fresh.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        # create_app -> limiter.init_app rebuilt the storage on the shared
        # limiter; start from empty buckets on the new app.
        limiter.reset()

        client = fresh.test_client()
        responses = [
            client.post(
                "/auth/login",
                data=_BAD_CREDS,
                headers={"X-Forwarded-For": "203.0.113.10"},
            )
            for _ in range(11)
        ]
        statuses = [r.status_code for r in responses]
        assert statuses == [401] * 10 + [429], (
            "the 203.0.113.10 bucket must exhaust at exactly 11 requests "
            f"(got {statuses})"
        )
        other = client.post(
            "/auth/login",
            data=_BAD_CREDS,
            headers={"X-Forwarded-For": "203.0.113.99"},
        )
        assert other.status_code == 401, (
            "TRUST_PROXY=1 must key the limiter on the X-Forwarded-For hop: "
            "a different forwarded client must get a fresh bucket, got "
            f"{other.status_code} (today the key is REMOTE_ADDR for every "
            "request — no ProxyFix/TRUST_PROXY wiring exists; finding #1)"
        )
    finally:
        monkeypatch.delenv("TRUST_PROXY", raising=False)
        importlib.reload(settings_mod)


# ---------------------------------------------------------------------------
# #2 — explicit 6/min on the ML portfolio endpoints
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path, service",
    [
        pytest.param(
            "/ai/forecast/portfolio?horizon=7&model=prophet",
            ForecastService,
            id="forecast",
        ),
        pytest.param(
            "/ai/anomaly/portfolio?contamination=0.07",
            AnomalyService,
            id="anomaly",
        ),
    ],
)
def test_portfolio_endpoints_429_after_6(app, monkeypatch, path, service):
    """#2 RED: both portfolio endpoints need an explicit 6 per minute.

    Neither route carries @limiter.limit today, so only the 200/min default
    applies and the 7th GET still returns 200 (the RED trigger). Requests
    1-6 must serve 200: flask-limiter counts in before_request, so an
    explicit limit trips the 429 BEFORE the view body runs — the stub below
    just keeps those first six responses cheap (cache cleared first so the
    stub path is deterministic).
    """
    import app.routes.ai as ai_mod

    ai_mod._portfolio_cache.clear()
    monkeypatch.setattr(service, "portfolio", _stub_portfolio)

    client = _session_client(app, "viewer")
    responses = [client.get(path) for _ in range(7)]
    statuses = [r.status_code for r in responses]
    assert statuses[:6] == [200] * 6, (
        f"{path} must serve the first 6 GETs, got {statuses[:6]}: "
        f"{responses[0].get_data(as_text=True)[:200]}"
    )
    assert statuses[6] == 429, (
        f"the 7th GET {path} must return 429 (explicit 6 per minute, "
        f"finding #2), got {statuses[6]} — default 200/min never trips at 7"
    )


# ---------------------------------------------------------------------------
# #3 — explicit 5/min on POST /monitoring/run-etl
# ---------------------------------------------------------------------------

def test_run_etl_429_after_5(app, monkeypatch):
    """#3 RED: POST /monitoring/run-etl needs @limiter.limit("5 per minute").

    ui.py imports etl_database from app.database.connection INSIDE the view,
    so monkeypatching the module attribute is the seam (the same one Issues
    03/06 rely on): the spawned _run threads call the no-op and no real ETL
    ever executes. Decorator order vs @login_required/@write_roles_required
    (finding #9) is cosmetic and deliberately unasserted — only the
    observable threshold is pinned: first five never 429, sixth exactly 429.
    When Issue 06's in-flight lock lands, early returns may change the first
    five's status codes, but they can never be 429 (counting happens in
    before_request, before the lock is even consulted).
    """
    import app.database.connection as conn_mod

    monkeypatch.setattr(
        conn_mod,
        "etl_database",
        lambda force=False: {"warehouse_etl_ok": True, "skipped": False},
    )
    client = _session_client(app, "manager")
    responses = [
        client.post("/monitoring/run-etl", follow_redirects=False)
        for _ in range(6)
    ]
    statuses = [r.status_code for r in responses]
    assert 429 not in statuses[:5], (
        f"threshold must be exactly 5 per minute — early 429 in {statuses[:5]}"
    )
    assert statuses[5] == 429, (
        "the 6th POST /monitoring/run-etl must return 429 (explicit 5 per "
        f"minute, finding #3), got {statuses[5]} — default 200/min never "
        f"trips at 6 (statuses: {statuses})"
    )


# ---------------------------------------------------------------------------
# #7 — JSON 429 envelope for /api/* (the page-route 429 stays HTML, pinned
# in test_login_429_after_10_bad_attempts)
# ---------------------------------------------------------------------------

def test_api_429_is_json_envelope(app):
    """#7 RED: an /api/* 429 must be the JSON envelope, not an HTML page.

    The shared errorhandler(429) in app/__init__.py always renders
    templates/errors/429.html (fallback: _fallback_page HTML) regardless of
    the request path — a JSON client gets text/html today. Uses an
    UNAUTHENTICATED client: the limiter runs in before_request, before
    login_required, so the first 30 cheap redirects/401s never touch the
    view or the DB.
    """
    client = app.test_client()
    responses = [client.post("/api/products", json={}) for _ in range(31)]
    statuses = [r.status_code for r in responses]
    assert 429 not in statuses[:30], (
        f"30/min tripped early: {statuses[:30]}"
    )
    last = responses[30]
    assert last.status_code == 429, (
        "31st POST /api/products must trip the 30/min limit, "
        f"got {last.status_code}"
    )
    assert last.is_json, (
        "/api/* 429 must be application/json (finding #7); got content-type "
        f"{last.content_type!r}"
    )
    payload = last.get_json()
    assert isinstance(payload, dict) and payload.get("success") is False, (
        f"429 envelope must be {{success: false, error: ...}}, got {payload!r}"
    )
    body = last.get_data(as_text=True).lower()
    assert "<!doctype" not in body and "<html" not in body, (
        f"API 429 leaked an HTML page: {body[:200]}"
    )


# ---------------------------------------------------------------------------
# #5 — RATELIMIT_STORAGE_URI wiring (env -> Config -> app.config)
# ---------------------------------------------------------------------------

def test_ratelimit_storage_uri_wired(app, monkeypatch):
    """#5 RED: RATELIMIT_STORAGE_URI must flow env -> Config -> app.config.

    Part (a): the session app's config must expose the key at all — today
    settings.py defines no such attribute, so the key is missing entirely.
    Part (b): the Config class body must read the env var (reload seam:
    class attributes are evaluated at import time). A memory://-style probe
    value only — no remote store connection is ever attempted here (finding
    #4 remains deferred). finally restores env AND pristine Config classes.
    """
    assert "RATELIMIT_STORAGE_URI" in app.config, (
        "Config must define RATELIMIT_STORAGE_URI (env-backed, default "
        "memory://) so flask-limiter can read it from app.config — the key "
        "is missing entirely today (finding #5: extensions.py hardcodes "
        'storage_uri="memory://" and settings.py has no such attribute)'
    )

    import app.config.settings as settings_mod

    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "memory://issue04-probe")
    importlib.reload(settings_mod)
    try:
        assert settings_mod.Config.RATELIMIT_STORAGE_URI == "memory://issue04-probe", (
            "Config.RATELIMIT_STORAGE_URI must be read from the "
            "RATELIMIT_STORAGE_URI environment variable at class-body time"
        )
    finally:
        monkeypatch.delenv("RATELIMIT_STORAGE_URI", raising=False)
        importlib.reload(settings_mod)


# ---------------------------------------------------------------------------
# #6 parity — explicit 30/min on PUT /api/settings (sanctioned cheap extra)
# ---------------------------------------------------------------------------

def test_settings_put_429_after_30(app):
    """#6 parity RED: PUT /api/settings needs @limiter.limit("30 per minute").

    Cheap probe: json={} is rejected with 422 before SettingsService runs
    (no DB write), so only the limit threshold can produce the 429 the 31st
    request expects — today the default 200/min lets it through (RED).
    """
    client = _session_client(app, "admin")
    responses = [client.put("/api/settings", json={}) for _ in range(31)]
    statuses = [r.status_code for r in responses]
    assert all(s in (400, 422) for s in statuses[:30]), (
        f"empty payload must fail validation before the threshold: {statuses[:30]}"
    )
    assert statuses[30] == 429, (
        "the 31st PUT /api/settings must return 429 (30 per minute parity "
        f"with the other API writes, finding #6), got {statuses[30]}"
    )
