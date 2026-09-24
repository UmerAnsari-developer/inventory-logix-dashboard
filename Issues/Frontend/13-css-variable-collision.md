# Frontend Issue Research: CSS Variable Collision (--ink)

> **Status: RESOLVED** (2026-09-24) — Mitigation implemented; verified in
> code review + full test suite (see docs/superpowers/plans/2026-09-22-frontend-issue-mitigation-plan.md,
> all checkboxes checked).
## Issue Reference
- Location: `landing.css:20`
- Description: The `--ink` CSS variable is defined in landing.css with a value that conflicts with its usage in the main application styles, causing styling conflicts

## How Dangerous Is This?
**Severity: High**
- Causes unpredictable styling where landing page styles override main app styles (or vice versa)
- Creates inconsistent appearance between landing page and authenticated application
- May cause important UI elements to become invisible or misstyled
- Results in brittle CSS that breaks when load order changes
- Particularly problematic as CSS variables are meant to provide consistent theming

## What Does It Cause?
1. **Style Conflicts**: Landing page CSS overrides main app CSS (or vice versa)
2. **Inconsistent Branding**: Visual inconsistency between public and private sections
3. **Unpredictable UI**: Depending on load order, different styles may apply
4. **Debugging Difficulty**: Hard to trace why certain elements have unexpected colors
5. **Fragile Architecture**: Small changes to CSS loading can break appearance
6. **Poor Maintainability**: Developers must remember which file "wins" for each variable
7. **Potential Accessibility Issues**: Accidental color changes could create contrast problems

## Root Cause Analysis
- Same CSS variable name (`--ink`) used in two different scopes with different intentions
- Landing page and main application likely intended to have separate variable scopes
- Missing CSS scoping strategy (like using :root for globals or component-specific prefixes)
- No CSS variable naming convention to prevent collisions
- Stylesheets may be loaded in overlapping contexts (e.g., landing.css also loaded in app)

## Mitigation Strategies
1. **Immediate Fix**: 
   - Rename the landing-specific `--ink` variable to something unique (e.g., `--landing-ink`)
   - Update all usages in landing.css to use the new variable name
   - Ensure main app `--ink` remains unchanged
2. **Better Approach**:
   - Establish CSS variable naming convention with prefixes:
     - `--global-` for truly global variables
     - `--layout-`, `--theme-`, `--component-` for scoped variables
     - Or use BEM-like naming: `--color-text-primary`, `--color-background-secondary`
   - Consider using CSS modules or CSS-in-JS for true scoping
   - Create CSS variable dictionary/documentation
3. **Preventive Measures**:
   - Add CSS variable linting to build process
   - Implement code review checklist for CSS variable usage
   - Train team on CSS scoping best practices
   - Consider adopting a CSS methodology (BEM, SMACSS, etc.)

## Implementation Plan
1. Examine `landing.css:20` to see current `--ink` definition
2. Determine if `--ink` is used elsewhere in landing.css that needs updating
3. Choose a new unique name for landing-specific ink variable (e.g., `--landing-ink-text`)
4. Update the definition and all usages in landing.css
5. Verify that landing page still styles correctly with new variable
6. Verify that main application is unaffected (should continue using its own `--ink`)
7. Check that no other CSS files inadvertently use the landing-specific variable

## Testing Approach
- Manual testing:
  - Visit landing page â†’ verify styling appears correct
  - Log in to application â†’ verify main app styling appears correct
  - Check that landing page styles don't "leak" into application (and vice versa)
  - Test responsive breakpoints on both landing and app
  - Verify that specific components using `--ink` in app still have correct colors
  - Use browser dev tools to inspect elements and confirm which variable is being applied
- Visual testing: Ensure no unexpected color changes appear anywhere

## Files to Modify/Create
- Modify: `app/static/css/landing.css` (line 20 and all usages of `--ink` within this file)
- Possibly: Create CSS variable documentation if none exists

## Dependencies
- Requires understanding of how `--ink` is used in both landing.css and main application
- Need to verify scope: is landing.css only used on landing page, or also in app?
- Should check base.html and other templates to see which CSS files are loaded where

## Estimated Effort
- 10-15 minutes to locate and rename variable
- 10-20 minutes to update usages and test
- Additional time if variable is used extensively in landing.css