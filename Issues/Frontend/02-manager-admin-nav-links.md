# Frontend Issue Research: Manager Sees Admin-Only Nav Links

> **Status: RESOLVED** (2026-09-24) — Mitigation implemented; verified in
> code review + full test suite (see docs/superpowers/plans/2026-09-22-frontend-issue-mitigation-plan.md,
> all checkboxes checked).
## Issue Reference
- Location: `app/templates/base.html:132` vs `roles_required("admin")`
- Description: Manager role users can see navigation links intended only for admin roles, leading to 403 Forbidden errors when clicked

## How Dangerous Is This?
**Severity: Critical**
- Creates false affordances (UI elements that appear actionable but lead to errors)
- Violates principle of least privilege in UI
- Causes confusion and frustration when users click links they shouldn't see
- Results in 403 errors that break user flow
- Potential security concern: reveals existence of admin-only features to non-admins

## What Does It Cause?
1. **403 Forbidden Errors**: When manager clicks admin-only nav links
2. **Broken Navigation Flow**: User expects to access feature but gets error instead
3. **User Confusion**: "Why can I see this link but not use it?"
4. **Increased Cognitive Load**: Users must remember which links are actually accessible
5. **Support Overhead**: Users report "access denied" on visible menu items
6. **Trust Erosion**: Makes permission system appear inconsistent or buggy

## Root Cause Analysis
- Navigation links in base.html are shown based on template-level conditions only
- No role-based filtering at the template level for admin-specific links
- Backend `roles_required("admin")` decorator correctly blocks access, but frontend shows links anyway
- Missing integration between backend role checks and frontend UI rendering

## Mitigation Strategies
1. **Immediate Fix**: Add role checks in base.html template to hide admin-only links from non-admins
2. **Better Approach**: 
   - Create template helper or context processor that provides user role/permissions
   - Use consistent role-checking mechanism across all templates
   - Consider feature flags or permission-based UI rendering
3. **Preventive Measures**:
   - Establish convention: all role-based UI restrictions handled in templates
   - Add template linting rule for hardcoded role checks
   - Create UI component library with built-in permission awareness

## Implementation Plan
1. Identify the 3 admin-only nav links in base.html around line 132
2. Wrap each with Jinja2 condition: `{% if current_user.has_role('admin') %}` or similar
3. Ensure the role-checking mechanism matches what `roles_required` decorator uses
4. Test with admin, manager, and viewer accounts
5. Consider creating a template macro for reusable role checks

## Testing Approach
- Login as admin: verify all 3 links visible and functional
- Login as manager: verify links are hidden (not just disabled)
- Login as viewer: verify links are hidden
- Attempt direct URL access as manager: should get 403 (backend protection still works)
- Verify no visual artifacts or layout shifts when links are hidden

## Files to Modify/Create
- Modify: `app/templates/base.html` (around line 132)

## Dependencies
- Requires understanding of current_user/role system in Flask app
- Need to check how roles are represented in templates (likely via Flask-Login or custom)

## Estimated Effort
- 10-20 minutes to locate links and add conditional wrappers
- Additional time for testing across roles