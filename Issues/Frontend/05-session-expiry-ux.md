# Frontend Issue Research: Missing Session Expiry UX

> **Status: RESOLVED** (2026-09-24) — Mitigation implemented; verified in
> code review + full test suite (see docs/superpowers/plans/2026-09-22-frontend-issue-mitigation-plan.md,
> all checkboxes checked).
## Issue Reference
- Location: Global JavaScript (implied from auth system behavior)
- Description: No user-facing indication when session expires; silent redirect to login loses form data and context

## How Dangerous Is This?
**Severity: High**
- Causes sudden loss of user work without warning
- Results in frustration when users lose unsaved form data
- Breaks user trust in application reliability
- Particularly problematic for lengthy forms (product creation, PO entry, etc.)
- Creates perception of unstable or "buggy" application

## What Does It Cause?
1. **Data Loss**: Users lose unsaved work when session expires mid-task
2. **Confusing UX**: Sudden redirect to login with no explanation
3. **Lost Productivity**: Time wasted redoing work that was lost
4. **Increased Support Tickets**: Users report "application kicked me out for no reason"
5. **Poor Accessibility**: Users with cognitive disabilities may find sudden context changes disorienting
6. **Reduced Trust**: Users become hesitant to start lengthy tasks fearing loss of work

## Root Cause Analysis
- Backend correctly enforces session timeout (Flask-Login or custom)
- Frontend lacks interceptors to detect 401/403 responses from AJAX requests
- No periodic session validity checking or warning system
- Missing UI patterns for session expiry handling (modals, countdowns, autosave warnings)

## Mitigation Strategies
1. **Immediate Fix**: 
   - Add Axios/Fetch interceptor to detect 401 responses from API calls
   - Show modal warning before redirecting to login
   - Attempt to save form data to localStorage before redirect
2. **Better Approach**:
   - Implement heartbeat/polling to check session status
   - Show countdown timer warning (e.g., "Your session expires in 2 minutes")
   - Implement autosave for forms to localStorage/indexedDB
   - Provide "Restore last session" option on login
3. **Preventive Measures**:
   - Establish frontend session handling standards
   - Create reusable auth service module with expiry warnings
   - Add session status indicator to UI (e.g., in header/footer)
   - Implement consistent timeout values across frontend/backend

## Implementation Plan
1. Identify where AJAX requests are made (likely in main.js or service files)
2. Add request/response interceptor to detect 401/403 status codes
3. When detected:
   - Show modal: "Your session has expired. Please log in again to continue."
   - Optionally: Save current form state to localStorage
   - Redirect to login page after user acknowledges
4. Consider adding idle timeout detection (no mouse/keyboard activity)
5. Test with various session expiry scenarios

## Testing Approach
- Manual testing: Log in, wait for session to expire (or force expiry)
- Verify warning appears before redirect to login
- Check that unsaved form data is preserved (if autosave implemented)
- Verify login process works normally after expiry redirect
- Test with different types of pages (forms, dashboards, etc.)
- Ensure normal operation unaffected when session is valid

## Files to Modify/Create
- Create/Modify: `app/static/js/main.js` or create new auth service file
- Possibly: `app/static/js/session-handler.js`
- Update: `app/templates/base.html` to include new script if needed

## Dependencies
- Requires understanding of current AJAX/fetch patterns in the application
- Need to check if there's already a central HTTP client wrapper
- Should coordinate with backend session timeout configuration

## Estimated Effort
- 30-45 minutes to implement interceptor and warning system
- Additional time for testing and polishing UX