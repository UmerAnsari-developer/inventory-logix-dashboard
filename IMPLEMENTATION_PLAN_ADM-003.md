# Implementation Plan: ADM-003 — In-Memory Rate Limiting Doesn't Scale (CRITICAL)

## Overview

Flask-Limiter currently uses `memory://` storage (in-process dictionary). With multiple workers (e.g., `gunicorn --workers=4`), each worker maintains its own independent rate-limit counter. An attacker can make N× the configured limit by distributing requests across workers. The fix is to switch to a shared Redis backend via `RATELIMIT_STORAGE_URI=redis://...` while preserving the existing PostgreSQL `rate_limit_state` table for AuthService lockout logic.

---

## Requirements

- **REQ-1**: Flask-Limiter must use a shared store (Redis) when `RATELIMIT_STORAGE_URI` points to Redis
- **REQ-2**: Single-worker deployments must continue working with `memory://` (no Redis required)
- **REQ-3**: Existing `rate_limit_state` PostgreSQL table for AuthService lockout must remain unchanged
- **REQ-4**: Startup warning when `workers>1` + `memory://` detected
- **REQ-5**: No schema migration needed (Redis is external)
- **REQ-6**: All existing rate limit thresholds preserved (10/min login, 5/min register, 30/min API writes, 60/min movements, 6/min portfolio, 5/min run-etl)

---

## Root Cause

**File**: `app/extensions.py` lines 16-20

```python
# storage backend comes from Config.RATELIMIT_STORAGE_URI via app.config —
# no storage_uri kwarg here (it would shadow flask-limiter's config lookup).
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute"],
)
```

The comment claims config lookup works, but Flask-Limiter's `init_app` prefers `self._storage_uri` (set by constructor kwarg) over `app.config["RATELIMIT_STORAGE_URI"]`. Since no `storage_uri` kwarg is passed, it defaults to `memory://` internally, **shadowing the config value entirely**.

**Evidence**: `tests/test_issue04_rate_limits.py` test `test_ratelimit_storage_uri_wired` (lines 462-490) is RED — it asserts the config key exists and is env-backed, but the limiter ignores it.

---

## Files/Components Affected

| File | Change Type | Description |
|------|-------------|-------------|
| `app/extensions.py` | **Modify** | Remove hardcoded `storage_uri` default; let Flask-Limiter read from `app.config["RATELIMIT_STORAGE_URI"]` |
| `app/config/settings.py` | **Verify** | Confirm `RATELIMIT_STORAGE_URI` reads from env at class-body time (already correct) |
| `app/__init__.py` | **Modify** | Add startup warning when `workers>1` detected with `memory://` |
| `requirements.txt` | **Add** | Add `redis>=5.0` dependency |
| `.env.example` | **Update** | Document Redis URI format and when to use it |
| `tests/test_issue04_rate_limits.py` | **Verify** | Existing test `test_ratelimit_storage_uri_wired` should turn GREEN |
| `tests/conftest.py` | **Verify** | Ensure test suite still works with `memory://` (no Redis in CI) |

---

## Database Objects Affected

| Object | Impact | Notes |
|--------|--------|-------|
| `rate_limit_state` table | **None** | Preserved for AuthService lockout (PostgreSQL-backed, correct) |
| `sp_retention_purge_rate_limit_state()` | **None** | Retention procedure unchanged |
| Redis keys | **New** | Flask-Limiter will create keys like `LIMITER/<key>/<window>` automatically |

**No schema migration needed** — Redis is external.

---

## Implementation Steps

### Phase 1: Fix Flask-Limiter Config Wiring (Smallest Safe Change)

#### Step 1.1: Remove shadowing in `app/extensions.py`
**File**: `app/extensions.py`  
**Action**: Ensure no `storage_uri` kwarg is passed to `Limiter()` constructor (already correct per comment, but verify)  
**Why**: Flask-Limiter's `init_app` reads `app.config["RATELIMIT_STORAGE_URI"]` only if `self._storage_uri` is not set. The current code has no kwarg, so this should work — but the test is RED, suggesting the config isn't being read.  
**Risk**: Low  
**Validation**: Run `test_ratelimit_storage_uri_wired` — should pass

#### Step 1.2: Verify `RATELIMIT_STORAGE_URI` in `app/config/settings.py`
**File**: `app/config/settings.py` line 66  
**Action**: Confirm `RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")` is at class-body level (it is)  
**Why**: Class attributes are evaluated at import time; env var must be read there for `importlib.reload` test to work  
**Risk**: Low  
**Validation**: Test `test_ratelimit_storage_uri_wired` part (b) passes

#### Step 1.3: Add `redis` to `requirements.txt`
**File**: `requirements.txt`  
**Action**: Add `redis>=5.0`  
**Why**: Required for `redis://` storage URI to work  
**Risk**: Low  
**Validation**: `pip install -r requirements.txt` succeeds; `import redis` works

---

### Phase 2: Startup Warning for Multi-Worker + Memory

#### Step 2.1: Detect worker count in `app/__init__.py`
**File**: `app/__init__.py` in `create_app()`  
**Action**: After `app.config.from_object(config_cls)`, check:
```python
import os
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))  # gunicorn sets this
if workers > 1 and app.config.get("RATELIMIT_STORAGE_URI", "memory://") == "memory://":
    import warnings
    warnings.warn(
        f"Running with {workers} workers but RATELIMIT_STORAGE_URI=memory://. "
        "Each worker has independent rate limits — attackers get {workers}x the limit. "
        "Set RATELIMIT_STORAGE_URI=redis://... for shared limiting.",
        RuntimeWarning,
        stacklevel=2
    )
```
**Why**: Gunicorn sets `WEB_CONCURRENCY`; other servers may not. This catches the common case.  
**Risk**: Low (warning only, no behavior change)  
**Validation**: Start app with `WEB_CONCURRENCY=4` and `memory://` — warning logged

---

### Phase 3: Documentation & Configuration

#### Step 3.1: Update `.env.example`
**File**: `.env.example` lines 21-25  
**Action**: Clarify when Redis is required:
```bash
# Rate limiting / cache-stampede shared storage.
# Default memory:// is correct for a single process (workers=1).
# When running workers>1 or instances>1, point this at Redis, e.g.:
# RATELIMIT_STORAGE_URI=redis://localhost:6379/0
# RATELIMIT_STORAGE_URI=redis://:password@redis-host:6379/0
RATELIMIT_STORAGE_URI=memory://
```
**Why**: Clear guidance for operators  
**Risk**: None  
**Validation**: Visual inspection

---

### Phase 4: Testing & Verification

#### Step 4.1: Run existing test suite
**Command**: `pytest tests/test_issue04_rate_limits.py -v`  
**Expected**: All tests GREEN (especially `test_ratelimit_storage_uri_wired`)  
**Why**: Validates config wiring works end-to-end

#### Step 4.2: Run full test suite
**Command**: `pytest`  
**Expected**: All tests pass (no regressions)  
**Why**: Ensures no side effects on auth, API limits, etc.

#### Step 4.3: Manual verification with Redis (optional, local)
**Action**: 
1. Start Redis: `docker run -d -p 6379:6379 redis:7`
2. Set `RATELIMIT_STORAGE_URI=redis://localhost:6379/0`
3. Run app with `gunicorn --workers=4 run:app`
4. Verify rate limits are shared across workers (e.g., 10 login attempts total, not 40)
**Why**: Confirms multi-worker fix works  
**Risk**: Medium (requires Redis) — can be skipped in CI

---

## Test Requirements

### Unit Tests (Existing — Must Stay GREEN)
- `test_login_429_after_10_bad_attempts` — 10/min login limit
- `test_register_429_after_5` — 5/min register limit
- `test_products_post_429_after_30` — 30/min API writes
- `test_movements_post_429_after_60` — 60/min movements
- `test_limits_keyed_per_remote_addr` — per-IP bucketing
- `test_xff_ignored_when_trust_proxy_off` — XFF spoof-proof by default
- `test_xff_trusted_when_trust_proxy_on` — XFF honored when `TRUST_PROXY=1`
- `test_portfolio_endpoints_429_after_6` — 6/min portfolio endpoints
- `test_run_etl_429_after_5` — 5/min run-etl
- `test_api_429_is_json_envelope` — JSON envelope for `/api/*` 429
- `test_ratelimit_storage_uri_wired` — **THIS IS THE KEY TEST** (env → Config → app.config)
- `test_settings_put_429_after_30` — 30/min PUT /api/settings

### Integration Tests (Existing — Must Stay GREEN)
- `tests/test_pg_rate_limiting.py` — PostgreSQL-backed AuthService lockout (unchanged)
- `tests/test_auth_lockout.py` — AuthService lockout flow
- `tests/test_admin_rate_limits.py` — Admin route limits

### Regression Tests (New — Add if Not Covered)
- **Test**: Startup warning emitted when `WEB_CONCURRENCY>1` + `memory://`
- **Test**: Rate limits shared across workers when Redis configured (manual/integration)

### Security Tests
- Verify XFF spoofing still blocked when `TRUST_PROXY=0` (existing test)
- Verify XFF honored when `TRUST_PROXY=1` (existing test)
- Verify `/api/*` 429 returns JSON envelope, not HTML (existing test)

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Redis connection failure crashes app | Low | High | Flask-Limiter falls back gracefully; add try/except in `create_app` if needed |
| `RATELIMIT_STORAGE_URI` misconfigured (typo) | Medium | Medium | Startup validation: test Redis connection on init if URI starts with `redis://` |
| Existing `memory://` tests break in CI | Low | High | CI runs single-worker; `memory://` remains default; no Redis in CI |
| AuthService lockout breaks | None | High | **No change to `rate_limit_state` table or AuthService** — completely separate |
| Gunicorn `WEB_CONCURRENCY` not set | Medium | Low | Warning only triggers when env var exists; default `1` is safe |
| Redis adds deployment complexity | Medium | Medium | Document clearly; `memory://` remains valid for single-worker |

---

## Security Considerations

1. **No weakening of limits**: All thresholds preserved exactly
2. **XFF handling unchanged**: `TRUST_PROXY` opt-in remains default OFF
3. **AuthService lockout isolated**: Uses PostgreSQL with advisory locks — unaffected by Flask-Limiter backend
4. **Redis auth**: Support `redis://:password@host:port/db` format in URI
5. **TLS**: Support `rediss://` for TLS (Flask-Limiter supports it via redis-py)
6. **Key isolation**: Flask-Limiter prefixes keys with `LIMITER/` — no collision with app Redis usage

---

## Rollback Considerations

| Component | Rollback Action |
|-----------|-----------------|
| `app/extensions.py` | Revert to previous version (no `storage_uri` kwarg was ever passed — just ensure config is read) |
| `requirements.txt` | Remove `redis>=5.0` line |
| `.env.example` | Revert documentation changes |
| `app/__init__.py` | Remove startup warning block |
| Redis server | Not required for rollback — `memory://` works without it |

**Rollback trigger**: If any existing test fails or rate limiting behaves incorrectly in staging.

---

## Expected Final Behavior

| Scenario | Before Fix | After Fix |
|----------|------------|-----------|
| Single worker, `memory://` | Works (1× limit) | Works (1× limit) — **unchanged** |
| 4 workers, `memory://` | **Broken** (4× limit) | Works but **warning logged** (4× limit still, but operator warned) |
| 4 workers, `redis://...` | N/A (not configured) | **Fixed** (1× limit shared across workers) |
| AuthService lockout | PostgreSQL (correct) | PostgreSQL (correct) — **unchanged** |
| `/api/*` 429 response | JSON envelope | JSON envelope — **unchanged** |
| Page-route 429 response | HTML template | HTML template — **unchanged** |
| `TRUST_PROXY=0` + XFF | Ignored (spoof-proof) | Ignored — **unchanged** |
| `TRUST_PROXY=1` + XFF | Honored | Honored — **unchanged** |

---

## Dependencies

- **Internal**: None (self-contained)
- **External**: `redis>=5.0` (PyPI), Redis server (optional, only for multi-worker)
- **Data**: None (no migration)

---

## Success Criteria

- [ ] `test_ratelimit_storage_uri_wired` passes (GREEN)
- [ ] All tests in `test_issue04_rate_limits.py` pass
- [ ] All tests in `test_pg_rate_limiting.py` pass
- [ ] Full test suite (`pytest`) passes
- [ ] Startup warning appears when `WEB_CONCURRENCY>1` + `memory://`
- [ ] No regression in AuthService lockout (PostgreSQL path)
- [ ] Redis connection works when `RATELIMIT_STORAGE_URI=redis://...` (manual verify)
- [ ] Documentation in `.env.example` is clear

---

## Implementation Order (Priority)

1. **Step 1.1** — Fix `app/extensions.py` (core fix, unblocks config)
2. **Step 1.3** — Add `redis` to `requirements.txt` (enables Redis URI)
3. **Step 2.1** — Add startup warning in `app/__init__.py` (operator safety)
4. **Step 3.1** — Update `.env.example` (documentation)
5. **Step 4.1** — Run `test_issue04_rate_limits.py` (validation)
6. **Step 4.2** — Run full test suite (regression check)

---

## Notes for Implementer

- **Do not modify** `app/services/auth_service.py` or `rate_limit_state` table — they are correct and separate
- **Do not add** a custom PostgreSQL storage backend for Flask-Limiter — Redis is the standard shared store
- **The test `test_ratelimit_storage_uri_wired` is the canonical validation** — if it passes, the wiring works
- **CI runs single-worker** — `memory://` is correct there; no Redis needed in CI
- **Production on Render free tier** — single worker, `memory://` is fine; Redis only needed when scaling