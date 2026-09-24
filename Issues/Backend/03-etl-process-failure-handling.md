# ETL Process Failure Handling

> **Status: RESOLVED** (2026-09-24) — Warehouse ETL folded into main
> transaction boundary (no more "main committed, warehouse failed" split);
> granular error reporting + idempotent rerun verified by
> `tests/test_issue03_regressions.py`. Full suite green.

## Issue Description
The ETL (Extract, Transform, Load) process lacks robust error handling and recovery mechanisms. When the ETL process fails partway through, it can leave the data warehouse in an inconsistent state, and there's no clear way to recover from partial failures.

## Affected Components
- `app/database/etl.py` - ETL implementation
- `app/database/connection.py` - Database connection handling used by ETL
- Related stored procedures and functions

## Failure Scenarios
1. **Partial ETL failure** - ETL process fails after updating some dimensions but before completing fact tables
2. **ETL process interruption** - Process killed or interrupted during execution
3. **Database connection loss during ETL** - Connection lost mid-ETL operation
4. **Inconsistent high-water mark** - The `last_movement_id` watermark updated incorrectly after partial failure
5. **Warehouse ETL failure** - Failure in the warehouse layer stored procedures

## Current Behavior
- ETL runs in a single database transaction (lines 396 in etl.py: `conn.commit()`)
- On any exception, the transaction is rolled back (line 399: `conn.rollback()`)
- However, the watermark (`last_movement_id`) is updated within the transaction, so it's rolled back too
- The warehouse ETL (`_run_warehouse_etl`) is called after the main ETL commit, so if it fails, the main ETL has already committed
- No retry mechanism for transient failures
- No detailed error reporting or recovery procedures

## Risk Assessment
- **Severity**: High
- **Can cause application crashes**: No (ETL is a background process)
- **Can cause incorrect data writes**: Yes (partial updates or inconsistent state)
- **Can cause duplicate operations**: No (design prevents duplicates)
- **Can cause state inconsistency**: Yes (data warehouse can be out of sync with operational data)
- **Can falsely report success**: Yes (if warehouse ETL fails after main ETL commits)
- **Is retry safe**: Yes, the ETL is designed to be idempotent
- **Is the operation idempotent**: Yes, ETL can be safely rerun
- **Is rollback/recovery possible**: Yes, by fixing the issue and rerunning ETL
- **Is the failure logged**: Yes, exceptions are logged
- **Is the failure observable**: Yes, through ETL logs and potentially stale dashboard data

## Evidence
- File: `app/database/etl.py`, lines 319-404 (`run_etl` function)
- File: `app/database/etl.py`, lines 390-395 (warehouse ETL call and error handling)
- File: `app/database/etl.py`, lines 396-404 (main transaction handling)

## Safe Simulation Plan
1. Simulate database connection loss during ETL execution
2. Test ETL recovery after fixing the underlying issue
3. Verify that partial failures don't leave inconsistent state
4. Test warehouse ETL failure handling

## Proposed Fix
1. Implement more granular transaction management for different ETL phases
2. Add retry logic for transient failures (especially network-related)
3. Improve error reporting and logging for ETL failures
4. Add validation checks after ETL completion to ensure consistency
5. Consider making the warehouse ETL part of the main transaction or adding compensation logic
6. Add metrics for ETL performance and failure rates

## Test Required After Change
- Test ETL recovery from various failure points
- Verify idempotency of ETL process
- Test error handling and logging
- Verify consistency between operational and warehouse data after ETL
- Test warehouse ETL failure handling