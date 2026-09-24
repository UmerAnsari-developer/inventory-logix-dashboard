# Frontend Issue Research: CDN Scripts Hang With No Timeout/Fallback

> **Status: RESOLVED** (2026-09-24) — Mitigation implemented; verified in
> code review + full test suite (see docs/superpowers/plans/2026-09-22-frontend-issue-mitigation-plan.md,
> all checkboxes checked).
## Issue Reference
- Location: `base.html` (CDN script includes for Plotly, Three.js, GSAP, etc.)
- Description: External CDN scripts loaded without timeout or fallback mechanisms, causing page to hang if CDN is unreachable or slow

## How Dangerous Is This?
**Severity: Medium**
- Causes complete page load failure or significant delay when CDN is inaccessible
- Results in poor user experience during CDN outages or network issues
- Makes application dependent on third-party service availability
- Particularly problematic for users behind restrictive firewalls or in regions with poor CDN connectivity
- Creates single point of failure for critical functionality (charts, 3D backgrounds, animations)

## What Does It Cause?
1. **Page Load Hangs**: Browser waits indefinitely for script to load
2. **Timeout-Dependent Failure**: Eventually fails after browser timeout (often very long)
3. **Broken Functionality**: Missing charts, 3D background, animations depending on which CDN failed
4. **Poor Perceived Performance**: Users see blank or incomplete page for extended periods
5. **Increased Support Burden**: Users report "application won't load" during CDN issues
6. **Loss of Critical Features**: 
   - Plotly: No data visualizations (dashboard, reports, forecasting)
   - Three.js: No animated background
   - GSAP: No UI animations and transitions
7. **Cascading Effects**: Depending on how scripts are used, missing dependencies may cause JS errors

## Root Cause Analysis
- Missing error handling for external resource loading
- No timeout mechanism on script tags (HTML limitation)
- No fallback to local copies or alternative CDNs
- Application assumes perfect availability of external dependencies
- No monitoring or alerting for CDN failures

## Mitigation Strategies
1. **Immediate Fix**: 
   - Add `timeout` attribute equivalent using JavaScript dynamic loading
   - Implement error handling for failed script loads
   - Add fallback to local copies of critical libraries
   - Consider deferring non-critical scripts
2. **Better Approach**:
   - Create script loader service with timeout, retries, and fallback
   - Implement progressive enhancement: basic functionality works without CDNs
   - Use service workers to cache CDN assets for offline resilience
   - Implement loading states and user feedback during script loading
   - Consider bundling critical dependencies with application (trade-off: larger initial load)
3. **Preventive Measures**:
   - Establish frontend policy for external dependencies
   - Monitor CDN performance and availability
   - Consider self-hosting critical JavaScript libraries
   - Add synthetic monitoring for key user journeys
   - Implement feature flags to disable non-essential features during CDN issues

## Implementation Plan
1. Identify all CDN script tags in `base.html`:
   - Plotly.js (for charts)
   - Three.js (for 3D background)
   - GSAP (for animations)
   - Any others (axios?, etc.)
2. Replace static `<script src="...">` tags with dynamic loading:
   - Create function `loadScriptWithTimeout(src, timeoutMs)`
   - Returns Promise that resolves when loaded or rejects on timeout/error
   - Implement retry logic (1-2 attempts) with exponential backoff
   - On success: insert script tag and resolve when loaded
   - On failure: attempt fallback to local copy if available
3. Handle loading states:
   - Show loading indicator while waiting for critical scripts
   - Disable functionality that depends on missing scripts gracefully
   - Show user-friendly message if critical features unavailable
4. Consider creating local fallback copies in `/static/js/vendor/` for critical libs
5. Update initialization code to wait for script loading promises

## Testing Approach
- Manual testing:
  - Simulate CDN failure: block domains in hosts file or use firewall rules
  - Verify page loads within timeout period instead of hanging
  - Verify fallback to local copy works if implemented
  - Test that dependent functionality degrades gracefully (e.g., no charts but basic layout works)
  - Verify normal operation when CDNs are available
  - Test timeout values: too short causes false failures, too long causes poor UX
- Network testing: Use Chrome DevTools to throttle network or block requests
- Test various failure scenarios: DNS failure, connection timeout, 404, 500 errors

## Files to Modify/Create
- Modify: `app/templates/base.html` (replace CDN script tags with dynamic loading)
- Create: `app/static/js/script-loader.js` (timeout/retry/fallback logic)
- Possibly: Create `/static/js/vendor/` directory for local fallback copies
- Modify: Initialization code that depends on these libraries to handle async loading

## Dependencies
- Requires understanding of when each CDN library is first used
- Need to ensure dependent code waits for scripts to load
- Should check if any libraries are loaded conditionally or only on certain pages
- May need to adjust initialization timing for components that use these libraries

## Estimated Effort
- 30-45 minutes to implement script loader and modify base.html
- 15-25 minutes to test failure scenarios and fallback behavior
- Additional time if local fallback copies need to be obtained and tested