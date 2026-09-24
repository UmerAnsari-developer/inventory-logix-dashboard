# Frontend Issue Research: Missing Offline/Timeout/Retry Handling

> **Status: RESOLVED** (2026-09-24) — Mitigation implemented; verified in
> code review + full test suite (see docs/superpowers/plans/2026-09-22-frontend-issue-mitigation-plan.md,
> all checkboxes checked).
## Issue Reference
- Location: Global JavaScript (AJAX/fetch calls throughout application)
- Description: No handling for network failures, request timeouts, or automatic retries

## How Dangerous Is This?
**Severity: High**
- Causes complete failure of user actions when network is unstable
- Results in poor user experience on mobile or flaky connections
- Users lose work or must manually retry failed operations
- Makes application feel unreliable in real-world conditions
- Particularly problematic for field workers using mobile hotspots or spotty WiFi

## What Does It Cause?
1. **Failed Requests**: Network errors cause requests to fail completely
2. **No User Feedback**: Errors often silent or show generic messages
3. **Manual Recovery Required**: Users must notice failure and retry manually
4. **Data Inconsistency Risk**: Partial failures may leave UI in unknown state
5. **Frustration on Mobile**: Poor experience for users on cellular networks
6. **Lost Productivity**: Time wasted retrying failed operations
7. **Perception of Brittleness**: Application seems unable to handle real-world conditions

## Root Cause Analysis
- Application assumes perfect network connectivity
- Missing wrapper around fetch/XHR calls for error handling
- No timeout configuration on requests (relying on browser defaults)
- No retry logic for transient failures
- No offline detection or queueing mechanism

## Mitigation Strategies
1. **Immediate Fix**: 
   - Add timeout parameters to fetch/XHR calls (e.g., 10-15 seconds)
   - Implement basic retry logic (1-2 attempts) for idempotent operations
   - Add offline detection using navigator.onLine
   - Show user-friendly error messages for network failures
2. **Better Approach**:
   - Create centralized HTTP service with timeout, retry, and error handling
   - Implement exponential backoff for retries
   - Add request queuing for offline operations (sync when back online)
   - Provide visual indicators for online/offline status
   - Implement background sync for critical operations
3. **Preventive Measures**:
   - Establish frontend networking standards
   - Create reusable API client library with built-in resilience
   - Add network error handling to code review checklist
   - Test regularly on throttled network conditions

## Implementation Plan
1. Identify central location for HTTP requests (main.js, service files, or individual components)
2. Create or enhance HTTP wrapper function:
   - Add timeout parameter (using AbortController for fetch)
   - Implement retry logic with configurable attempts
   - Add error classification (network vs HTTP error vs timeout)
   - Return consistent error objects to callers
3. Add offline detection:
   - Listen to online/offline events
   - Optionally queue certain actions for later execution
4. Update all HTTP calls to use the enhanced wrapper
5. Test with various network conditions

## Testing Approach
- Manual testing: 
  - Disconnect network during request â†’ should show error, not hang
  - Use Chrome DevTools network throttling (Slow 3G, offline)
  - Verify timeout behavior with delayed server responses
  - Test retry logic with intermittent failures
  - Verify success when network restored
- Automated testing: Consider adding network condition tests to test suite

## Files to Modify/Create
- Create: `app/static/js/http-client.js` (enhanced fetch wrapper)
- Modify: `app/static/js/main.js` and other files to use new client
- Possibly: `app/static/js/offline-handler.js` for queueing
- Update: `app/templates/base.html` to include new scripts

## Dependencies
- Requires survey of all AJAX/fetch usage in the application
- Need to identify which requests are idempotent (safe to retry)
- Should coordinate with backend API design (ensure endpoints are safe for retries)

## Estimated Effort
- 45-60 minutes to create HTTP client and update usage
- Additional time for testing across network conditions
- May require updating multiple files throughout static/js/