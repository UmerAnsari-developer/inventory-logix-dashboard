# Frontend Issue Research: Filter Bar Z-Index Stacking Context

> **Status: RESOLVED** (2026-09-24) — Mitigation implemented; verified in
> code review + full test suite (see docs/superpowers/plans/2026-09-22-frontend-issue-mitigation-plan.md,
> all checkboxes checked).
## Issue Reference
- Location: style.css (mentioned in UI layering gotchas)
- Description: `.filter-bar` and `.report-filter-row` need `position: relative; z-index: 30` to prevent `.table-scroll` from painting over their dropdowns due to stacking context issues

## How Dangerous Is This?
**Severity: Medium**
- Causes dropdown menus to be hidden behind table scrolling elements
- Makes filter controls unusable when tables are present on same page
- Creates inconsistent UI where some dropdowns work and others don't
- Particularly problematic on pages with both filters and data tables (inventory, reports, etc.)
- Results in poor user experience where users cannot access filter options

## What Does It Cause?
1. **Hidden Dropdowns**: Filter dropdowns render behind table elements and are inaccessible
2. **Broken Functionality**: Users cannot change filter values when dropdowns are obscured
3. **Inconsistent UI**: Some filter dropdowns work (on pages without overlapping tables) while others don't
4. **User Confusion**: "Why won't this dropdown open?" when it's actually hidden behind table
5. **Increased Support Tickets**: Users report "filter dropdowns not working"
6. **Poor Usability**: Violates principle that interactive elements should be accessible and visible
7. **Workaround Dependency**: Users may need to resize windows or change layout to access controls

## Root Cause Analysis
- Missing stacking context management for overlapping UI components
- `.table-scroll` likely creates its own stacking context (due to overflow or transform)
- Dropdowns appear in normal flow but get painted behind elements with higher stacking context
- No z-index management strategy for UI layers (background, content, overlays, etc.)
- Common issue when combining fixed-position headers, scrolling containers, and dropdowns

## Mitigation Strategies
1. **Immediate Fix**: 
   - Add `position: relative; z-index: 30` to `.filter-bar` and `.report-filter-row` in style.css
   - Verify that this resolves the overlapping issue without causing new problems
   - Check that z-index 30 is appropriate relative to other stacked elements (headers, modals, etc.)
2. **Better Approach**:
   - Establish z-index hierarchy or layering system for the application
   - Define layers: background (-10), content (0), fixed header (10), dropdowns (30), modals (100), overlays (200)
   - Use CSS custom properties for z-index values: `--z-index-dropdown: 30`
   - Consider using stacking context containers rather than relying on z-index alone
3. **Preventive Measures**:
   - Add UI layering checklist to frontend development process
   - Create visual regression tests for overlapping UI components
   - Train team on stacking contexts and z-index management
   - Consider implementing a CSS architecture methodology (ITCSS, BEM, etc.)

## Implementation Plan
1. Locate `.filter-bar` and `.report-filter-row` selectors in `app/static/css/style.css`
2. Add `position: relative; z-index: 30;` to both selectors
3. Verify that:
   - Dropdowns now appear above table scrolling elements
   - No other UI elements are incorrectly hidden or obscured
   - z-index 30 doesn't conflict with higher-priority elements like modals or headers
   - Position relative doesn't break layout of the filter bars themselves
4. Test on pages that contain both filters and tables:
   - Inventory page (filters + inventory table)
   - Reports page (filters + results table)
   - Any other pages with this combination
5. Test dropdown functionality: click, hover, keyboard navigation

## Testing Approach
- Manual testing:
  - Navigate to inventory page with active filters
  - Open filter dropdowns â†’ verify they appear above table, not behind it
  - Test with long dropdown lists that might extend below the filter bar
  - Verify table scrolling still works normally behind dropdowns
  - Test on reports page similarly
  - Check that header, sidebar, and other UI elements still layer correctly
  - Test with browser zoom levels (110%, 125%, etc.)
  - Test responsive behavior: ensure fix works on mobile/tablet views
- Edge case: Test with multiple overlapping components (filter over table over modal)

## Files to Modify/Create
- Modify: `app/static/css/style.css` (add position and z-index to .filter-bar and .report-filter-row)

## Dependencies
- Requires understanding of current z-index usage in the application
- Need to check if z-index 30 conflicts with any existing usages
- Should verify that position: relative doesn't break flex/grid layouts if used
- May need to adjust if filtering is implemented differently in various places

## Estimated Effort
- 5-10 minutes to locate selectors and add CSS
- 10-15 minutes for testing across affected pages
- Additional time if z-index adjustments needed for other components