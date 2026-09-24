# Frontend Issue Research: Missing aria-invalid and Accessible Error Wiring

> **Status: RESOLVED** (2026-09-24) — Mitigation implemented; verified in
> code review + full test suite (see docs/superpowers/plans/2026-09-22-frontend-issue-mitigation-plan.md,
> all checkboxes checked).
## Issue Reference
- Location: All forms throughout application
- Description: Zero use of `aria-invalid` attribute and missing accessible error messaging for form validation failures

## How Dangerous Is This?
**Severity: High**
- Makes form validation inaccessible to screen reader users
- Violates WCAG 2.1 accessibility guidelines (particularly SC 1.3.1, 3.3.1, 3.3.3)
- Creates exclusionary experience for users with disabilities
- May expose organization to accessibility compliance risks
- Results in poor user experience for 15-20% of population with disabilities

## What Does It Cause?
1. **Screen Reader Inaccessibility**: Users cannot tell which fields have errors
2. **Lack of Error Context**: Screen readers announce fields but not associated error messages
3. **Violation of Accessibility Standards**: Fails WCAG 2.1 AA requirements for form validation
4. **Exclusion of Disabled Users**: Prevents effective use by people relying on assistive technology
5. **Poor Universal Design**: Misses opportunity to improve UX for all users (clear error association helps everyone)
6. **Legal/Compliance Risk**: Potential violation of accessibility laws in many jurisdictions

## Root Cause Analysis
- Missing consideration of accessibility in form implementation
- Error messages likely inserted into DOM without proper association to form fields
- No use of ARIA attributes to link errors to their corresponding fields
- Accessibility not included in definition of "done" for UI features

## Mitigation Strategies
1. **Immediate Fix**: 
   - Add `aria-invalid="true"` to invalid form fields
   - Associate error messages with fields using `aria-describedby` pointing to error element ID
   - Ensure error messages are visible and announced by screen readers
2. **Better Approach**:
   - Implement accessible pattern for form validation:
     - Field becomes `aria-invalid="true"` when invalid
     - Error message has unique ID
     - Field's `aria-describedby` includes the error message ID
     - Error message is live region or announced on change
   - Create reusable accessible form component patterns
   - Ensure error messages are clear, concise, and helpful
3. **Preventive Measures**:
   - Add accessibility checklist to UI development process
   - Include screen reader testing in QA procedures
   - Establish ARIA usage standards for common UI patterns
   - Consider partnering with accessibility experts for audit

## Implementation Plan
1. Audit all form validation points (both HTML5 and JavaScript validation)
2. For each field that can show validation errors:
   - Ensure error message container has unique ID (e.g., `email-error`, `password-error`)
   - When field is invalid:
     - Set `aria-invalid="true"` on the field element
     - Update field's `aria-describedby` to include the error message ID
   - When field becomes valid:
     - Set `aria-invalid="false"` (or remove attribute)
     - Remove error message ID from `aria-describedby`
3. Ensure error messages are styled to be visible (not just for screen readers)
4. Test with screen reader software (NVDA, JAWS, or built-in VoiceOver/Narrator)

## Testing Approach
- Manual testing with screen reader:
  - Navigate to form with invalid field
  - Verify screen reader announces field name, state, and error message
  - Test with NVDA (free) or built-in OS screen reader
  - Verify announcement occurs when field gains focus
  - Test dynamic updates: when error appears/disappears, announcement updates
- Verify visual appearance still works correctly
- Test that valid fields don't incorrectly announce as invalid
- Check that error messages are sufficiently descriptive

## Files to Modify/Create
- Modify: Form templates throughout application where validation occurs
- Possibly: Create `app/static/js/accessible-forms.js` helper for ARIA management
- Update: JavaScript validation logic to include ARIA attribute updates

## Dependencies
- Requires survey of all form validation implementation points
- Need to understand current error messaging mechanism
- Should coordinate with any JavaScript validation being added (from issue #8)

## Estimated Effort
- 30-45 minutes to audit and implement accessible error wiring
- Additional time for screen reader testing
- May touch many files but changes are localized to validation points