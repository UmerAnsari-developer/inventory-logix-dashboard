# Frontend Issue Research: Asset Version Query Parameters Must Be Bumped

> **Status: RESOLVED** (2026-09-24) — Mitigation implemented; verified in
> code review + full test suite (see docs/superpowers/plans/2026-09-22-frontend-issue-mitigation-plan.md,
> all checkboxes checked).
## Issue Reference
- Location: `base.html` (asset includes with query params like `style.css?v=20.3`)
- Description: CSS and JavaScript files include version query parameters that must be manually incremented when files change, otherwise browsers serve cached stale versions

## How Dangerous Is This?
**Severity: Medium (Process Risk)**
- Causes users to see outdated JavaScript/CSS after deployment
- Leads to bugs that appear to be "fixed" but actually persist due to stale cache
- Creates inconsistency between what developers see and what users experience
- Results in increased support tickets for "old" issues that were supposedly fixed
- Wastes developer time debugging issues that are actually cache-related
- Particularly problematic for frequent deployments or hotfixes

## What Does It Cause?
1. **Stale Cache Issues**: Users retain old versions of CSS/JS files after deploy
2. **Inconsistent Behavior**: Different users see different versions based on cache state
3. **False Bug Reports**: Issues appear to persist after fix due to caching
4. **Debugging Complexity**: Time wasted investigating issues that are actually cache-related
5. **Deployment Anxiety**: Fear that fixes won't reach users due to caching
6. **Increased Support Overhead**: Need to instruct users to hard-refresh or clear cache
7. **Poor User Experience**: Users may encounter mixed old/new interface elements

## Root Cause Analysis
- Manual process for updating version query parameters is error-prone
- No automated asset versioning in build/deployment process
- Missing integration between build system and HTML template updates
- Developers forget to bump versions or bump them incorrectly
- No validation that version numbers match actual file content

## Mitigation Strategies
1. **Immediate Fix**: 
   - Establish strict process: always bump version when changing CSS/JS
   - Add deployment checklist item: verify version numbers in base.html
   - Consider using semantic versioning or incremental numbers for clarity
2. **Better Approach**:
   - Implement automated cache busting in build process:
     - Use file hashes or timestamps as version numbers
     - Generate base.html template during build with correct versions
     - Implement using build tools (webpack, gulp, etc.) or simple scripts
   - Consider using HTTP caching headers (ETag, Last-Modified) instead of query params
   - Implement service worker for more sophisticated caching control
3. **Preventive Measures**:
   - Add version checking to CI/CD pipeline
   - Create deployment automation that handles asset versioning
   - Train team on importance of cache busting
   - Consider adopting frontend build tooling for long-term maintainability

## Implementation Plan
1. Identify all assets with version query parameters in base.html:
   - CSS files: style.css, landing.css, ai-features.css, eoq.js?, main.js?, landing.js?
   - JavaScript files: auth-bg.js, dashboard-3d.js, saas-animations.js, ai-features.js, eoq.js, main.js, landing.js
2. Establish version bumping convention:
   - Option A: Increment decimal (20.3 â†’ 20.4) for each change
   - Option B: Use timestamp (v=1663852800)
   - Option C: Use git commit hash (v=abc123def)
   - Option D: Use file content hash (most accurate but requires build step)
3. For immediate term: continue manual process with increased vigilance
4. For better term: implement build step that:
   - Reads file contents or timestamps
   - Generates correct query parameters
   - Injects them into base.html template
5. Add verification step to deployment process

## Testing Approach
- Manual testing:
  - Change a CSS or JS file
  - Bump version number in base.html
  - Deploy change
  - Verify new users get updated file (check network tab)
  - Verify old cached version is not served
  - Test hard-refresh behavior still works
- Process testing:
  - Audit recent commits: did CSS/JS changes always include version bump?
  - Create pre-commit hook to warn if CSS/JS changed but version not bumped?
  - Test deployment pipeline for version consistency

## Files to Modify/Create
- Modify: `app/templates/base.html` (update version numbers when assets change)
- Possibly: Create version bumping script or integrate with build process
- If implementing automated solution: modify build/deployment scripts

## Dependencies
- Requires discipline from development team to remember version bumps
- Need to audit all assets that use version query parameters
- Should verify that changing version parameter actually busts cache (it does for most browsers)
- Consider impact on CDN caching if used

## Estimated Effort
- 5-10 minutes per asset change to bump version (ongoing cost)
- 30-60 minutes to implement automated solution (if pursued)
- Additional time for team training and process establishment