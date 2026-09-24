# Frontend Issue Research: Inventory Pagination Drops Active Filters/Search

> **Status: RESOLVED** (2026-09-24) — Mitigation implemented; verified in
> code review + full test suite (see docs/superpowers/plans/2026-09-22-frontend-issue-mitigation-plan.md,
> all checkboxes checked).
## Issue Reference
- Location: `inventory.html:110,114`
- Description: When navigating inventory pagination, active filters and search terms are lost, forcing users to reapply filters on each page

## How Dangerous Is This?
**Severity: High**
- Creates frustrating user experience when browsing large datasets
- Causes loss of work context when users need to navigate through filtered results
- Inefficient: forces users to reapply same filters repeatedly
- Particularly problematic for inventory management where users often filter by category, supplier, status, etc.
- Leads to missed items as users may give up on deep pagination due to friction

## What Does It Cause?
1. **Lost Context**: Users forget what filters were applied when jumping between pages
2. **Inefficient Workflow**: Must reapply filters on every page change
3. **Increased Cognitive Load**: Users must remember filter state externally
4. **Risk of Oversight**: Users may stop paginating early due to frustration, missing items
5. **Poor Usability**: Violates principle of maintaining user state during navigation
6. **Increased Support Calls**: Users report "pagination doesn't remember my filters"

## Root Cause Analysis
- Pagination links or JavaScript do not preserve current query parameters
- Likely hardcoded pagination URLs that reset to default state
- Missing mechanism to merge current filters/search with pagination actions
- Backend may support filtering via query parameters but frontend doesn't persist them

## Mitigation Strategies
1. **Immediate Fix**: 
   - Modify pagination links to include current query parameters (filters, search, sort)
   - Use `window.location.href` manipulation or form-based filtering with hidden inputs
   - Ensure pagination controls preserve existing GET parameters
2. **Better Approach**:
   - Implement state management for filter UI (URL-based or client-side state)
   - Use HTML5 History API to update URL without full reload when filters change
   - Create reusable pagination component that automatically preserves query state
   - Implement smart URL parsing to maintain state across navigations
3. **Preventive Measures**:
   - Establish frontend state persistence standards for list views
   - Create reusable table/pagination component with built-in state preservation
   - Add URL state testing to frontend QA checklist
   - Consider implementing client-side filtering for instant response (with server fallback)

## Implementation Plan
1. Analyze current inventory filtering mechanism (likely query parameters like `?category=X&search=Y`)
2. Locate pagination controls in `inventory.html` around lines 110 and 114
3. Modify pagination link generation to include current query parameters:
   - Extract current query string from `window.location.search`
   - Append or merge with pagination parameters (page number)
   - Generate URLs like `/inventory?category=electronics&search=chip&page=2`
4. Ensure form-based filtering (if used) uses GET method to populate URL
5. Test that changing filters updates URL, and pagination preserves those changes

## Testing Approach
- Manual testing:
  - Apply filters (category, supplier, date range, search term)
  - Verify URL updates to reflect filters
  - Navigate to page 2, 3, etc. via pagination controls
  - Verify filters remain applied on each page
  - Test that removing filters works correctly
  - Test combination of multiple filters and sorting
  - Verify back/forward browser buttons work correctly with filtered state
- Edge case: Test with special characters in search terms (need URL encoding)

## Files to Modify/Create
- Modify: `app/templates/inventory.html` (around lines 110 and 114)
- Possibly: Create `app/static/js/pagination-helper.js` for URL parameter manipulation
- If filtering is form-based: ensure form uses `method="get"`

## Dependencies
- Requires understanding of current inventory filtering implementation
- Need to check if backend already supports filtering via query parameters (it likely does)
- Should verify that preserving query parameters doesn't break anything

## Estimated Effort
- 15-25 minutes to locate and modify pagination controls
- 10-15 minutes for testing across filter combinations
- Additional time if form-based filtering needs adjustment