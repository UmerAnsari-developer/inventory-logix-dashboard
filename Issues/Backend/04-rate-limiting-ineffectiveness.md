# Rate Limiting Ineffectiveness in Distributed Deployments

> **Status: RESOLVED (as designed)** (2026-09-24) — `RATELIMIT_STORAGE_URI`
> already env-configurable (`app/config/settings.py:66`); default `memory://`
> is correct for single-instance. `.env.example` now documents switching to
> Redis when `workers>1 or instances>1` (the documented trigger). No code
> change needed — config was already right, docs were the gap.

## Issue Description
The current rate limiting implementation uses in-memory storage which is ineffective in distributed deployments (multiple application instances), allowing users to exceed rate limits by distributing requests across instances.

## Affected Components
- `app/extensions.py` - Rate limiter initialization
- `app/__init__.py` - Extension initialization
- All API endpoints that use `@limiter.limit()` decorators

## Failure Scenarios
1. **Distributed deployment ineffectiveness** - In multi-instance deployments (e.g., multiple Gunicorn workers or multiple servers), each instance maintains its own rate limit counters
2. **Rate limit bypass** - Users can make N times the allowed requests where N is the number of instances
3. **Inconsistent rate limiting** - Different users experience different effective rate limits based on which instance they hit
4. **Memory bloat** - Each instance maintains its own copy of all rate limit data

## Current Behavior
- Rate limiter initialized in `extensions.py` with `storage_uri="memory://"` (line 19)
- This creates a separate in-memory store for each Python process
- In production with multiple Gunicorn workers or multiple servers, each has independent rate limiting
- No coordination between instances for rate limit tracking

## Risk Assessment
- **Severity**: Medium
- **Can cause application crashes**: No
- **Can cause incorrect data writes**: Yes (could allow abuse leading to excessive database writes)
- **Can cause duplicate operations**: Yes (could allow exceeding intended limits on write operations)
- **Can cause state inconsistency**: No
- **Can falsely report success**: No
- **Is retry safe**: N/A
- **Is the operation idempotent**: N/A
- **Is rollback/recovery possible**: N/A
- **Is the failure logged**: No specific logging for rate limit bypass
- **Is the failure observable**: Yes, through increased load and potential abuse

## Evidence
- File: `app/extensions.py`, lines 16-20 (limiter initialization)
- File: `app/__init__.py`, line 169 (extension initialization)
- Multiple API routes in `app/routes/api.py` with `@limiter.limit()` decorators

## Safe Simulation Plan
1. Deploy multiple instances of the application (or simulate with multiple processes)
2. Send requests exceeding the per-instance rate limit but distributed across instances
3. Verify that the combined request rate exceeds the intended limit
4. Observe lack of effective rate limiting

## Proposed Fix
1. Change the rate limiter storage to use a shared backend like Redis
2. Update the `storage_uri` in `extensions.py` to point to a shared Redis instance
3. Ensure Redis is available and configured in production deployments
4. Add fallback behavior for when Redis is unavailable
5. Monitor rate limiting effectiveness in distributed deployments

## Test Required After Change
- Verify rate limiting works correctly in single-instance mode
- Verify rate limiting works correctly across multiple instances
- Test fallback behavior when shared storage is unavailable
- Verify performance impact of shared storage is acceptable
- Test that legitimate users are not incorrectly rate limited