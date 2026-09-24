# Background Job Failure Recovery

> **Status: RESOLVED** (2026-09-24) — Recovery implemented against the
> `etl_warehouse_state` key-value rows (`etl_job_status` / `etl_job_error` /
> `warehouse_etl_ok`), NOT a new `etl_job_runs` table. Full test suite green
> (`tests/test_issue06_job_recovery.py`). Design note kept below for context.

## Issue Description
Background jobs (like the ETL process triggered via the `/monitoring` endpoint) lack robust failure detection, recovery mechanisms, and proper error reporting, making it difficult to identify and recover from failures.

## Affected Components
- `app/routes/ui.py` - Monitoring route that triggers ETL
- `app/services/monitoring_service.py` - Monitoring service implementation
- `app/database/etl.py` - ETL process
- `app/utils/cache.py` - Monitoring cache
- Lack of background job tracking/monitoring system

## Failure Scenarios
1. **Silent background job failure** - ETL process fails but user sees no indication of failure
2. **No failure recovery** - Failed jobs don't automatically retry
3. **Incomplete status reporting** - Monitoring page doesn't accurately reflect job status
4. **Resource leaks** - Failed jobs may leave resources locked or in inconsistent state
5. **Lack of operational visibility** - Operators cannot easily see if background jobs are running successfully

## Current Behavior
- The `/monitoring` endpoint has a "Run ETL" button that triggers `etl_database()` in a non-blocking thread (from `app/routes/ui.py`)
- The ETL process runs and logs results, but there's no persistent tracking of job status
- The monitoring page shows "ETL status" and "DB stats" but these may not reflect recent failures
- No job queue, no retry mechanism, no alerting on failure
- If the ETL thread fails, the failure is logged but not surfaced to users in a actionable way

## Risk Assessment
- **Severity**: Medium
- **Can cause application crashes**: No
- **Can cause incorrect data writes**: Yes (failed ETL can leave warehouse in inconsistent state)
- **Can cause duplicate operations**: No
- **Can cause state inconsistency**: Yes (data warehouse not updated with latest data)
- **Can falsely report success**: Yes (monitoring may show stale data as current)
- **Is retry safe**: Yes, ETL is designed to be idempotent
- **Is the operation idempotent**: Yes
- **Is rollback/recovery possible**: Yes, by fixing issue and rerunning
- **Is the failure logged**: Yes, ETL logs failures
- **Is the failure observable**: Limited - requires checking logs or noticing stale data

## Evidence
- File: `app/routes/ui.py`, lines that handle the "Run ETL" button (need to find exact location)
- File: `app/database/etl.py` - ETL implementation
- File: `app/utils/cache.py` - `monitoring_cache` used for DB stats
- File: `app/services/monitoring_service.py` - Monitoring service

## Safe Simulation Plan
1. Trigger an ETL failure (e.g., by temporarily making database unavailable)
2. Verify that the failure is properly logged
3. Check what status is shown to users in the monitoring interface
4. Verify that users have no easy way to know the ETL failed
5. Test recovery after fixing the underlying issue

## Proposed Fix
1. Implement a background job tracking system with persistent status
2. Add job metadata (start time, end time, status, error messages, etc.)
3. Expose job status through the monitoring API/interface
4. Implement automatic retry with exponential backoff for failed jobs
5. Add alerting/notification for repeated failures
6. Add metrics for job success/failure rates and duration
7. Consider using a proper background job queue (like Celery) for complex workflows

## Resolution (applied)

- Job status persisted in existing `etl_warehouse_state` KV rows — no new table.
- `/monitoring` Run ETL remains non-blocking thread; status/error surfaced from KV.
- Retry: ETL is idempotent (`migrate.py etl` / button rerun) — no Celery queue added
  (YAGNI at current scale; trigger queue adoption when workers>1 or jobs>1min p95).
- Covered by `tests/test_issue06_job_recovery.py` (green in full suite).

## Test Required After Change
- Verify job tracking works correctly
- Test failure detection and reporting
- Verify recovery process works
- Test automatic retry functionality
- Ensure job status is accurately reflected in monitoring interface
- Test that legitimate job successes are properly recorded