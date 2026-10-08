# Implementation Plan: ADM-002 - Admin Session Timeout Enforcement Decoupling

## Overview

The admin session timeout enforcement is currently coupled to the `roles_required` decorator in `app/security/roles.py`. This means routes protected only by `@login_required` (without `@roles_required`) bypass the admin session timeout check entirely. The fix moves timeout enforcement to a `before_request` middleware that checks all `/admin/*` paths for admin users, ensuring consistent timeout enforcement regardless of route decorators.

## Requirements

- [ ] Admin session timeout enforced on ALL `/admin/*` routes for admin users
- [ ] Manager users on `/admin/*` routes use regular session timeout (no admin timeout)
- [ ] Non-admin routes unaffected (use regular session timeout)
- [ ] Existing `ADMIN_SESSION_TIMEOUT_MINUTES` config preserved (default 30 min)
- [ ] No double-check on routes already using `@roles_required("admin")`
- [ ] No schema migration needed
- [ ] Must not break manager access to admin routes
- [ ] Must work with existing `before_request` handlers in `app/__init__.py`

## Root Cause

The timeout logic lives in `roles_required` decorator at `app/security/roles.py:27-39`:
```python
if current_user.role == "admin":
    # timeout check and session update
```
This only executes when the decorator is applied. Routes with only `@login_required` skip this check entirely.

## Files/Components Affected

| File | Change Type | Description |
|------|-------------|-------------|
| `app/__init__.py` | **Add** | New `before_request` middleware for admin session timeout |
| `app/security/roles.py` | **Modify** | Remove timeout logic from `roles_required` (keep role check only) |
| `tests/test_admin_session_timeout.py` | **Modify** | Update tests to verify middleware behavior |
| `tests/test_roles.py` | **Modify** | Add tests for role decorator without timeout logic |

## Database Objects Affected

**None** - No schema changes required. Session data stored in Flask session cookie.

## Implementation Steps

### Phase 1: Add Middleware in `create_app()` (Smallest Safe Change)

**1. Add admin timeout middleware** (File: `app/__init__.py`)
- **Action**: Add a new `@app.before_request` handler after existing handlers (after line 102) that:
  - Checks if `request.path.startswith("/admin/")`
  - Checks if `current_user.is_authenticated and current_user.role == "admin"`
  - If both true, enforces `ADMIN_SESSION_TIMEOUT_MINUTES` timeout
  - Updates `session["admin_last_activity"]` on each request
  - Aborts with 403 if timeout exceeded
- **Why**: Centralizes timeout enforcement at the request level, independent of route decorators
- **Dependencies**: None (runs in `create_app()`)
- **Risk**: Low - additive change, doesn't modify existing logic
- **Validation**: Admin user accessing `/admin/dashboard/` gets timeout enforced; manager accessing same route uses regular timeout

**2. Remove timeout logic from `roles_required`** (File: `app/security/roles.py`)
- **Action**: Delete lines 27-39 (the admin timeout check block), keep only the role check (lines 23-24)
- **Why**: Eliminates double-check on routes with `@roles_required("admin")`; middleware handles it
- **Dependencies**: Requires Step 1 complete (middleware must be active)
- **Risk**: Medium - removes existing enforcement; must verify middleware catches all cases
- **Validation**: Routes with `@roles_required("admin")` still enforce timeout via middleware

### Phase 2: Test Updates

**3. Update `test_admin_session_timeout.py`** (File: `tests/test_admin_session_timeout.py`)
- **Action**: 
  - Add test verifying middleware enforces timeout on `/admin/*` for admin users
  - Add test verifying managers on `/admin/*` use regular timeout
  - Add test verifying non-admin routes unaffected
  - Update `test_admin_routes_enforce_session_timeout` to test middleware directly
- **Why**: Ensures new middleware behavior is tested
- **Dependencies**: Steps 1-2 complete
- **Risk**: Low - test updates only
- **Validation**: All tests pass

**4. Add tests to `test_roles.py`** (File: `tests/test_roles.py`)
- **Action**: Add test verifying `roles_required` no longer contains timeout logic (only role check)
- **Why**: Regression prevention - ensures timeout logic doesn't creep back into decorator
- **Dependencies**: Step 2 complete
- **Risk**: Low
- **Validation**: Test passes

### Phase 3: Verification

**5. Manual verification checklist**
- [ ] Admin user: `/admin/dashboard/` enforces 30-min timeout
- [ ] Admin user: `/admin/users/` enforces 30-min timeout
- [ ] Manager user: `/admin/dashboard/` uses regular session (no admin timeout)
- [ ] Viewer user: `/admin/dashboard/` returns 403 (role check)
- [ ] Regular route `/` for admin: uses regular session timeout
- [ ] Session `admin_last_activity` updates on each admin request
- [ ] Expired admin session redirects to login with "Admin session expired" message

## Testing Strategy

### Unit Tests
- `test_admin_session_timeout.py::test_admin_session_timeout_config_exists` - config exists
- `test_admin_session_timeout.py::test_admin_session_timeout_shorter_than_regular` - config value
- `test_roles.py` - new test: `roles_required` only checks role, not timeout

### Integration Tests
- `test_admin_session_timeout.py::test_admin_routes_enforce_session_timeout` - middleware enforces on `/admin/*`
- `test_admin_session_timeout.py::test_manager_on_admin_routes_uses_regular_timeout` - managers unaffected
- `test_admin_session_timeout.py::test_non_admin_routes_unaffected` - regular routes use regular timeout
- `test_admin_session_timeout.py::test_admin_session_refresh_on_activity` - activity updates timestamp

### E2E Tests (Manual)
- Login as admin, wait 31 minutes (or mock time), access `/admin/dashboard/` → 403
- Login as manager, access `/admin/dashboard/` → 200 (if manager has access) or 403 (role check)
- Login as admin, access `/` (non-admin) → 200, no admin timeout check

### Security Tests
- Verify timeout cannot be bypassed by accessing admin routes without `@roles_required`
- Verify session fixation not possible (new session on login)
- Verify `admin_last_activity` not exposed in client-side code

### Performance Tests
- Middleware adds <1ms overhead per request (simple path check + session read)
- No additional DB queries

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Middleware runs before `login_required`, causing errors on unauthenticated requests | Low | Medium | Check `current_user.is_authenticated` first |
| Double timeout check on routes with `@roles_required("admin")` | Medium | Low | Remove timeout from decorator (Step 2) |
| Manager users incorrectly get admin timeout | Low | High | Explicit check `current_user.role == "admin"` only |
| Breaking existing admin routes | Low | High | All admin routes use `/admin/*` prefix; test all |
| Session race condition (concurrent requests) | Low | Low | Flask session is request-scoped; last write wins is acceptable |
| Config `ADMIN_SESSION_TIMEOUT_MINUTES` not respected | Low | Medium | Use `current_app.config["ADMIN_SESSION_TIMEOUT_MINUTES"]` |

## Security Considerations

- **Timeout value**: Uses existing `ADMIN_SESSION_TIMEOUT_MINUTES` (default 30 min) - shorter than regular 7-day session
- **Session storage**: `admin_last_activity` stored in signed Flask session cookie (HttpOnly, Secure, SameSite=Lax)
- **Error message**: "Admin session expired. Please log in again." - no information leakage
- **Role check**: Only `role == "admin"` triggers timeout; managers use regular session
- **Path matching**: `request.path.startswith("/admin/")` - covers all admin blueprints
- **No persistent cookies**: Sessions end on browser close (per AGENTS.md: "Login sets ONLY a browser-session cookie")

## Rollback Plan

### Database
- No database changes to rollback

### Code
1. Revert `app/__init__.py`: Remove the added `before_request` middleware
2. Revert `app/security/roles.py`: Restore timeout logic in `roles_required` (lines 27-39)
3. Revert test changes in `tests/test_admin_session_timeout.py` and `tests/test_roles.py`

### Configuration
- No config changes (uses existing `ADMIN_SESSION_TIMEOUT_MINUTES`)

## Expected Final Behavior

| User Role | Route Pattern | Timeout Applied |
|-----------|---------------|-----------------|
| admin | `/admin/*` | `ADMIN_SESSION_TIMEOUT_MINUTES` (30 min) |
| admin | `/api/*`, `/`, `/products/*`, etc. | Regular session (7 days) |
| manager | `/admin/*` | Regular session (7 days) |
| manager | Other routes | Regular session (7 days) |
| viewer | `/admin/*` | 403 Forbidden (role check) |
| viewer | Other routes | Regular session (7 days) |

**Session Flow for Admin on `/admin/*`:**
1. Request hits middleware
2. Middleware checks: path starts with `/admin/` AND user is admin
3. Reads `session["admin_last_activity"]`
4. If expired → clear timestamp, abort 403
5. If valid → update `session["admin_last_activity"] = now`
6. Continue to route handler

**No Double-Check:** Routes with `@roles_required("admin")` only perform role check; middleware handles timeout.

## Dependencies

- **Internal**: None (self-contained in `create_app()` and `roles.py`)
- **External**: None
- **Data**: None

## Success Criteria

- [ ] All existing tests pass (`pytest tests/`)
- [ ] New middleware tests pass
- [ ] Admin timeout enforced on `/admin/*` without `@roles_required`
- [ ] Manager access to `/admin/*` works (role permitting)
- [ ] No double timeout check on decorated routes
- [ ] Config `ADMIN_SESSION_TIMEOUT_MINUTES` respected
- [ ] Manual verification checklist complete
- [ ] Security review passes (no session fixation, no info leakage)