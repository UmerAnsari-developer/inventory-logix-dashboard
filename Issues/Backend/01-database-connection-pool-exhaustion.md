# Database Connection Pool Exhaustion

> **Status: RESOLVED** (2026-09-24) — Lazy health-check + stale-connection
> retry added (no per-request `SELECT 1` ping); `get_pool_stats()` sanitized
> so pool keys can no longer leak DSN/password. Full suite green.

## Issue Description
Under high concurrent load, the database connection pool can become exhausted, leading to connection acquisition failures and 500 errors for users.

## Affected Components
- `app/database/connection.py` - Connection pooling implementation
- `app/__init__.py` - Bootstrap database connection
- All database operations via `get_connection()` and `get_cursor()`

## Failure Scenarios
1. **Database connection pool exhaustion** - When all connections in the pool are checked out and not returned
2. **Stale connections in pool** - Connections that become invalid but remain in the pool
3. **Connection leak** - Connections not properly returned to pool after use
4. **Database restart/recovery** - Pool contains stale connections after database restart

## Current Behavior
- Connection pool size is fixed at `_POOL_SIZE = 10` in `connection.py`
- On checkout, connections are validated with `SELECT 1` but only once
- On stale-connection error during cursor operations, connection is replaced and operation retried once
- No automatic pool resizing or connection recycling based on usage patterns
- No connection timeout enforcement for idle connections

## Risk Assessment
- **Severity**: High
- **Can cause application crashes**: Yes (500 errors when pool exhausted)
- **Can cause incorrect data writes**: No (failed connections don't write data)
- **Can cause duplicate operations**: No (failed at connection level)
- **Can cause state inconsistency**: No
- **Can falsely report success**: No
- **Is retry safe**: Yes, at the operation level (with idempotent operations)
- **Is the operation idempotent**: Depends on the specific operation
- **Is rollback/recovery possible**: Yes, failed connections don't commit
- **Is the failure logged**: Yes, connection errors are logged
- **Is the failure observable**: Yes, through 500 errors and logs

## Evidence
- File: `app/database/connection.py`, lines 107-125 (`get_connection()` function)
- File: `app/database/connection.py`, lines 128-167 (`get_cursor()` function)
- File: `app/database/connection.py`, line 36: `_POOL_SIZE = 10`

## Safe Simulation Plan
1. Set `_POOL_SIZE = 1` in `connection.py`
2. Simulate high concurrent load with multiple simultaneous requests
3. Observe connection exhaustion errors
4. Verify error handling and recovery

## Proposed Fix
1. Increase default pool size based on expected concurrent users
2. Implement connection idle timeout to recycle stale connections
3. Add connection leak detection and logging
4. Implement adaptive pool sizing based on usage patterns
5. Add metrics for pool utilization monitoring

## Test Required After Change
- Verify pool size configuration is respected
- Test connection exhaustion handling
- Verify stale connection detection and replacement
- Test connection leak detection
- Verify normal operation with increased pool size