# Cache Stampede Protection Missing

> **Status: RESOLVED** (2026-09-24) — Per-key stampede lock already present
> in `TTLCache.get_or_set` (`app/utils/cache.py`); `_rebuild_locks` growth
> marked with `ponytail:` comment (bounded by active key churn at current
> scale). `tests/test_issue05_stampede.py` green.

## Issue Description
The caching implementation lacks protection against cache stampede (also known as thundering herd) when popular cache entries expire, potentially causing sudden spikes in database load and degraded performance.

## Affected Components
- `app/utils/cache.py` - TTLCache implementation with `get_or_set` method
- All cached database queries throughout the application
- Particularly impactful for expensive queries like reports and dashboard data

## Failure Scenarios
1. **Cache stampede** - When a popular cached entry expires, multiple concurrent requests all miss the cache and simultaneously execute the expensive producer function
2. **Database overload** - Sudden spike in identical expensive queries can overwhelm the database
3. **Increased latency** - All waiting requests experience high latency until one producer completes
4. **Resource exhaustion** - Can lead to connection pool exhaustion or other resource depletion

## Current Behavior
- The `get_or_set` method in `TTLCache` uses a per-key lock to prevent thundering herd (lines 55-68)
- However, this implementation has a potential issue: the lock is created and stored in `_rebuild_locks` but never cleaned up
- Under high churn of different keys, `_rebuild_locks` can grow indefinitely
- The locking mechanism prevents multiple threads from executing the producer for the same key, but doesn't address the broader thundering herd problem effectively

## Risk Assessment
- **Severity**: Medium
- **Can cause application crashes**: Yes (under extreme load, could exhaust resources)
- **Can cause incorrect data writes**: No
- **Can cause duplicate operations**: Yes (multiple threads may still execute producer if locking fails)
- **Can cause state inconsistency**: No
- **Can falsely report success**: No
- **Is retry safe**: N/A
- **Is the operation idempotent**: Depends on the producer function
- **Is rollback/recovery possible**: N/A
- **Is the failure logged**: No specific logging for cache stampede events
- **Is the failure observable**: Yes, through sudden latency spikes and increased database load

## Evidence
- File: `app/utils/cache.py`, lines 49-68 (`get_or_set` method)
- File: `app/utils/cache.py`, lines 27-28 (class docstring mentions preventing thundering herd)
- File: `app/utils/cache.py`, line 56: `_rebuild_locks` dictionary that grows without bound

## Safe Simulation Plan
1. Identify a popular cached endpoint with expensive backend operation
2. Set a short TTL on that cache entry
3. Simulate concurrent requests hitting the endpoint just as the cache expires
4. Measure the number of simultaneous backend executions
5. Verify locking effectiveness

## Proposed Fix
1. Implement a more robust cache stampede protection mechanism (e.g., probabilistic early expiration)
2. Add cleanup mechanism for `_rebuild_locks` to prevent memory leak
3. Consider adding metrics for cache hit/miss and stampede events
4. Add logging when cache stampede protection is activated
5. Consider using a more sophisticated caching library or Redis with built-in protections

## Test Required After Change
- Verify that cache stampede protection works correctly
- Test that the `_rebuild_locks` dictionary doesn't leak memory
- Verify performance under normal conditions
- Test under simulated stampede conditions
- Ensure legitimate cache operations are not negatively impacted