# Authentication Service Race Condition

> **Status: RESOLVED** (2026-09-24) — Per-user lock now spans
> gate→verify→append atomically; audit + log writes moved OUTSIDE the lock
> (no DB roundtrip while holding it). `_utcnow()` clock seam added. Covered
> by `tests/test_auth_lockout.py` (7 tests, green).

## Issue Description
The authentication service uses in-memory data structures for failed login tracking that are susceptible to race conditions under high concurrent load, potentially allowing brute force attacks or incorrectly locking accounts.

## Affected Components
- `app/services/auth_service.py` - Authentication service implementation
- Specifically the `_failed_logins` dictionary and `_lockout_mutex` locking mechanism

## Failure Scenarios
1. **Race condition in failed login tracking** - Concurrent login attempts for the same user can bypass the lockout mechanism
2. **Inconsistent lockout state** - Due to improper locking, the failed login count can become inaccurate
3. **Lockout bypass** - Attackers can make more attempts than allowed due to race conditions
4. **False lockouts** - Legitimate users can be locked out due to race conditions in clearing failed attempts

## Current Behavior
- Uses a `defaultdict(list)` for `_failed_logins` to track failed attempts by user ID
- Uses a single `_lockout_mutex` (threading.Lock) for synchronization
- On failed login: locks mutex, prunes old attempts, checks count, adds new attempt, unlocks
- On successful login: locks mutex, clears failed attempts for user, unlocks
- The locking mechanism appears correct but needs verification for edge cases

## Risk Assessment
- **Severity**: Medium
- **Can cause application crashes**: No
- **Can cause incorrect data writes**: Yes (incorrect failed login tracking)
- **Can cause duplicate operations**: No
- **Can cause state inconsistency**: Yes (inconsistent authentication state)
- **Can falsely report success**: Yes (could allow unauthorized access)
- **Can falsely report failure**: Yes (could lock out legitimate users)
- **Is retry safe**: N/A (this is about the protection mechanism itself)
- **Is the operation idempotent**: N/A
- **Is rollback/recovery possible**: Yes, state can be corrected
- **Is the failure logged**: No specific logging for race conditions
- **Is the failure observable**: Difficult to observe directly; would manifest as security issues

## Evidence
- File: `app/services/auth_service.py`, lines 24-30 (failed login tracker initialization)
- File: `app/services/auth_service.py`, lines 66-86 (authenticate method locking logic)
- File: `app/services/auth_service.py`, lines 84-86 (clearing failed attempts on success)

## Safe Simulation Plan
1. Create a test that simulates concurrent login attempts for the same user
2. Verify that the lockout mechanism works correctly under concurrency
3. Test both successful and failed login scenarios under load
4. Verify that the failed login count remains accurate

## Proposed Fix
1. Consider using a thread-safe data structure or more granular locking
2. Add logging for lockout events and failed login attempts
3. Consider moving to a distributed cache (like Redis) for failed login tracking in multi-instance deployments
4. Add metrics for authentication events (successful logins, failed logins, lockouts)

## Test Required After Change
- Unit tests for concurrent access to failed login tracking
- Integration tests simulating brute force attacks under load
- Verify lockout timing is correct
- Verify that legitimate users are not incorrectly locked out