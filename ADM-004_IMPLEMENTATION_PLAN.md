# Implementation Plan: ADM-004 — Backup Restore Thread Lock Only In-Process (CRITICAL)

## Overview

The backup restore operation currently uses `threading.Lock()` (`_RESTORE_RUN_LOCK`) which only serializes restores within a single Python process. When running with multiple workers (e.g., Gunicorn with `workers > 1`), concurrent restores can execute simultaneously across different worker processes, causing database corruption. The fix replaces the in-process lock with a PostgreSQL advisory lock (like ETL uses with `_ETL_LOCK_KEY = 774001`), using a distinct key (`774002`) to avoid conflicts.

## Requirements

- [ ] Replace `threading.Lock()` with PostgreSQL advisory lock for cross-process serialization
- [ ] Use distinct lock key `774002` (ETL uses `774001`)
- [ ] Acquire lock in main thread before spawning background thread
- [ ] Release lock in background thread's `finally` block
- [ ] Handle connection lifecycle properly (advisory locks are session-scoped)
- [ ] Maintain backward compatibility with single-worker deployments
- [ ] All existing tests pass
- [ ] New tests verify cross-process serialization

## Root Cause

**File**: `app/services/backup_service.py`, line 31
```python
_RESTORE_RUN_LOCK = threading.Lock()
```

**Problem**: `threading.Lock()` is process-local. With multiple Gunicorn workers, each worker has its own lock instance. Two concurrent restore requests hitting different workers will both acquire their local lock and proceed simultaneously, corrupting the database during `pg_restore`.

**Evidence**: Code comment at lines 29-31 acknowledges this:
```python
# DB-031: in-process in-flight guard for restore — correct
# for the single-worker profile; switch to pg_try_advisory_lock when workers > 1
_RESTORE_RUN_LOCK = threading.Lock()
```

## Files/Components Affected

| File | Change Type | Description |
|------|-------------|-------------|
| `app/services/backup_service.py` | **Primary** | Replace `_RESTORE_RUN_LOCK` with advisory lock logic; modify `restore_backup()` to acquire/release via DB |
| `app/database/connection.py` | **Reference** | Use `_open_conn()` pattern for long-running background operations (no statement_timeout) |
| `tests/test_backup_restore_transaction.py` | **Test** | Add tests for advisory lock behavior |
| `tests/test_backup_encryption.py` | **Test** | Verify existing encryption tests still pass |

## Database Objects Affected

| Object | Type | Impact |
|--------|------|--------|
| `pg_try_advisory_lock(774002)` | Function | New advisory lock key for restore serialization |
| `pg_advisory_unlock(774002)` | Function | Release advisory lock |
| `etl_warehouse_state` | Table | Already used for restore job status persistence (no change) |

**No schema changes required** — advisory locks are built-in PostgreSQL functions.

## Implementation Steps

### Phase 1: Core Lock Replacement (Smallest Safe Change)

#### Step 1: Add Advisory Lock Constants and Helpers
**File**: `app/services/backup_service.py`
- Add `_RESTORE_LOCK_KEY = 774002` constant (distinct from ETL's `774001`)
- Add helper functions `_acquire_restore_lock(conn)` and `_release_restore_lock(conn)`
- Use `_open_conn()` from `app.database.connection` for background thread (no statement_timeout)

**Action**:
```python
# Add after line 31 (after _RESTORE_RUN_LOCK comment)
_RESTORE_LOCK_KEY = 774002  # Distinct from ETL's 774001

def _acquire_restore_lock(conn) -> bool:
    """Try to acquire PostgreSQL advisory lock for restore.
    Returns True if acquired, False if another restore is running.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s) AS locked", (_RESTORE_LOCK_KEY,))
        return cur.fetchone()["locked"]

def _release_restore_lock(conn) -> None:
    """Release PostgreSQL advisory lock for restore."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", (_RESTORE_LOCK_KEY,))
```

**Dependencies**: None
**Risk**: Low — additive only, no behavior change yet
**Validation**: Unit test helper functions in isolation

#### Step 2: Modify `restore_backup()` to Use Advisory Lock in Main Thread
**File**: `app/services/backup_service.py`, function `restore_backup()` (lines 309-495)

**Current flow**:
1. Validate backup exists
2. Try `threading.Lock().acquire(blocking=False)` → fail if busy
3. Capture app context
4. Start background thread `_run()` which releases lock in `finally`

**New flow**:
1. Validate backup exists
2. Open dedicated connection via `_open_conn()` (bypasses pool, no statement_timeout)
3. Try `pg_try_advisory_lock(774002)` → fail if busy
4. **If acquired**: Start background thread, passing the connection
5. **If not acquired**: Close connection, return "another restore in progress"
6. Background thread uses same connection, releases lock in `finally`, then closes connection

**Action**: Replace lines 333-338 (lock acquire) and lines 476-477 (lock release) with advisory lock logic.

**Dependencies**: Step 1
**Risk**: Medium — changes connection lifecycle in background thread
**Validation**: Integration test with mocked DB connection

#### Step 3: Update Background Thread `_run()` to Use Passed Connection
**File**: `app/services/backup_service.py`, inner function `_run()` (lines 368-477)

**Changes**:
- Accept `conn` parameter instead of creating new connections
- Use passed connection for all DB operations (`_persist`, checksum verification, etc.)
- Release advisory lock in `finally` block before closing connection
- Handle connection errors gracefully

**Dependencies**: Step 2
**Risk**: Medium — connection management in background thread
**Validation**: Integration test verifying lock release on success/failure/exception

#### Step 4: Remove `threading.Lock` Import and Variable
**File**: `app/services/backup_service.py`
- Remove `import threading` (line 8) if no longer used elsewhere
- Remove `_RESTORE_RUN_LOCK = threading.Lock()` (line 31)

**Dependencies**: Steps 1-3 complete
**Risk**: Low — cleanup only
**Validation**: Lint check, no unused imports

### Phase 2: Connection Lifecycle Hardening

#### Step 5: Ensure Connection Cleanup on All Paths
**File**: `app/services/backup_service.py`

**Verify**:
- Lock acquired → thread starts → thread releases lock → closes connection ✓
- Lock acquired → thread fails to start → main thread releases lock → closes connection ✓
- Lock not acquired → main thread closes connection immediately ✓
- Background thread exception → `finally` releases lock → closes connection ✓

**Action**: Add explicit `try/finally` in main thread for connection cleanup when thread start fails.

**Dependencies**: Step 3
**Risk**: Low — defensive coding
**Validation**: Code review, integration test with thread start failure simulation

#### Step 6: Handle Stale Locks from Dead Connections
**File**: `app/services/backup_service.py`

**Action**: At start of `restore_backup()`, before acquiring lock, release any stale lock on the new connection (mirrors ETL pattern at `etl.py:488`):
```python
conn = _open_conn()
try:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", (_RESTORE_LOCK_KEY,))
    # Now try to acquire...
```

**Dependencies**: Step 2
**Risk**: Low — defensive, matches ETL pattern
**Validation**: Test with simulated stale lock scenario

### Phase 3: Testing

#### Step 7: Unit Tests for Advisory Lock Helpers
**File**: `tests/test_backup_restore_transaction.py` (or new `test_backup_advisory_lock.py`)

**Tests**:
- `_acquire_restore_lock()` returns `True` when lock free
- `_acquire_restore_lock()` returns `False` when lock held
- `_release_restore_lock()` releases lock (subsequent acquire succeeds)
- Lock key `774002` distinct from ETL's `774001`

**Dependencies**: Step 1
**Risk**: Low
**Validation**: `pytest tests/test_backup_advisory_lock.py -v`

#### Step 8: Integration Test — Single Restore Succeeds
**File**: `tests/test_backup_restore_transaction.py`

**Test**: Full restore flow with advisory lock — acquires lock, runs background, releases lock, returns success.

**Dependencies**: Steps 1-3
**Risk**: Medium
**Validation**: `pytest tests/test_backup_restore_transaction.py::TestBackupRestoreTransaction::test_restore_validates_checksum_before_restore -v`

#### Step 9: Integration Test — Concurrent Restore Blocked
**File**: `tests/test_backup_restore_transaction.py`

**Test**: Simulate two concurrent `restore_backup()` calls — second should return "another restore in progress" immediately.

**Dependencies**: Steps 1-3
**Risk**: Medium
**Validation**: New test `test_concurrent_restore_blocked_by_advisory_lock`

#### Step 10: Integration Test — Lock Released on Background Failure
**File**: `tests/test_backup_restore_transaction.py`

**Test**: Background thread raises exception → lock released → subsequent restore can acquire lock.

**Dependencies**: Steps 1-3
**Risk**: Medium
**Validation**: New test `test_restore_lock_released_on_background_failure`

#### Step 11: Regression Test — Existing Encryption/Checksum Tests Pass
**File**: `tests/test_backup_encryption.py`

**Action**: Run full test suite to ensure no regressions.

**Dependencies**: All implementation steps
**Risk**: Low
**Validation**: `pytest tests/test_backup_encryption.py -v`

## Testing Strategy

| Test Type | Coverage | Command |
|-----------|----------|---------|
| **Unit** | Advisory lock helpers (`_acquire_restore_lock`, `_release_restore_lock`) | `pytest tests/test_backup_advisory_lock.py -v` |
| **Integration** | Full restore flow with advisory lock | `pytest tests/test_backup_restore_transaction.py -v` |
| **Integration** | Concurrent restore blocked (cross-process simulation) | `pytest tests/test_backup_restore_transaction.py::test_concurrent_restore_blocked_by_advisory_lock -v` |
| **Integration** | Lock released on background thread failure | `pytest tests/test_backup_restore_transaction.py::test_restore_lock_released_on_background_failure -v` |
| **Regression** | All existing backup encryption tests | `pytest tests/test_backup_encryption.py -v` |
| **E2E** | Manual: Start 2 Gunicorn workers, trigger concurrent restores via UI | Manual verification |

**Coverage Target**: ≥80% for new/modified code in `backup_service.py`

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| **Connection leak in background thread** | Medium | High | Use `try/finally` with explicit `conn.close()`; mirror ETL pattern |
| **Stale advisory lock from crashed worker** | Low | Medium | Release stale lock at start of `restore_backup()` (ETL pattern) |
| **Lock contention with ETL (same key)** | None | High | Use distinct key `774002` vs ETL's `774001` |
| **Statement timeout kills long restore** | Medium | High | Use `_open_conn()` (no statement_timeout) for background thread |
| **Pool exhaustion from long-held connections** | Low | Medium | Background thread uses dedicated connection, not pool |
| **Single-worker regression** | Low | Medium | Advisory locks work identically in single-process; test both modes |

## Security Considerations

- **No new attack surface**: Advisory locks are internal PostgreSQL functions, no user input involved
- **Lock key is constant**: `774002` hardcoded, not user-controllable
- **Connection credentials**: Uses existing `_open_conn()` which reads from Flask config/env — no new credential handling
- **Error messages**: Sanitized via existing `_safe_error()` (from ETL) — no stack traces or DSN leakage

## Rollback Considerations

### Database Rollback
- **No schema changes** — advisory locks require no DDL
- **No data migration** — purely runtime behavior change
- **Rollback**: Revert `backup_service.py` to use `threading.Lock()`

### Code Rollback
```bash
# Revert single file
git checkout HEAD -- app/services/backup_service.py

# Revert tests
git checkout HEAD -- tests/test_backup_restore_transaction.py
```

### Configuration Rollback
- No configuration changes required
- Works with existing `DATABASE_URL` and pool settings

## Expected Final Behavior

| Scenario | Before (threading.Lock) | After (pg_advisory_lock) |
|----------|------------------------|--------------------------|
| Single worker, sequential restores | ✅ Works | ✅ Works |
| Single worker, concurrent restores | ✅ Blocked (in-process) | ✅ Blocked (DB-level) |
| Multi-worker, sequential restores | ✅ Works | ✅ Works |
| **Multi-worker, concurrent restores** | ❌ **Both proceed → corruption** | ✅ **Second blocked → safe** |
| Restore crashes mid-operation | Lock leaked (thread dies) | Lock auto-released (session ends) |
| Worker restarts during restore | Lock leaked | Lock auto-released (session ends) |

## Dependencies

- **Internal**: ETL advisory lock pattern (`app/database/etl.py`), connection helpers (`app/database/connection.py`)
- **External**: PostgreSQL 9.6+ (advisory locks supported since 9.6)
- **Data**: None — no migration needed

## Success Criteria

- [ ] All unit tests pass (`pytest tests/test_backup_advisory_lock.py`)
- [ ] All integration tests pass (`pytest tests/test_backup_restore_transaction.py`)
- [ ] All regression tests pass (`pytest tests/test_backup_encryption.py`)
- [ ] Manual E2E test: 2 Gunicorn workers, concurrent restores → second blocked
- [ ] Security review: No secrets in code, error messages sanitized
- [ ] Performance: Lock acquire/release < 5ms overhead
- [ ] Documentation: Code comments updated to reflect cross-process safety

---

**Plan Author**: Planner Agent
**Date**: 2026-09-26
**Status**: Ready for Implementation