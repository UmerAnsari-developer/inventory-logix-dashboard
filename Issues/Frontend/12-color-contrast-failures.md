# Frontend Issue Research: Color Contrast Failures (WCAG AA)

> **Status: RESOLVED** (2026-09-24) — Mitigation implemented; verified in
> code review + full test suite (see docs/superpowers/plans/2026-09-22-frontend-issue-mitigation-plan.md,
> all checkboxes checked).
## Issue Reference
- Location: style.css / landing.css (general throughout application)
- Description: Color combinations that fail to meet WCAG 2.1 AA contrast ratio requirements (4.5:1 for normal text, 3:1 for large text)

## How Dangerous Is This?
**Severity: High**
- Makes text difficult or impossible to read for users with visual impairments
- Affects approximately 1 in 12 men (8%) and 1 in 200 women with color vision deficiency
- Creates poor user experience for aging users and those in challenging lighting conditions
- Violates accessibility laws and guidelines in many jurisdictions
- Results in exclusionary design that violates principles of universal access

## What Does It Cause?
1. **Reduced Readability**: Text blends with background, causing eye strain and misreading
2. **Accessibility Exclusion**: Prevents effective use by people with low vision or color blindness
3. **WCAG Non-Compliance**: Fails to meet legal accessibility requirements in many regions
4. **Poor Universal Design**: Misses opportunity to improve readability for all users
5. **Increased Cognitive Load**: Users must work harder to decipher information
6. **Potential Safety Issues**: In industrial/inventory contexts, misreading data could lead to errors
7. **Brand Perception Issues**: Reflects poorly on application quality and attention to detail

## Root Cause Analysis
- Color choices likely made based on aesthetic preferences without accessibility testing
- Missing accessibility review in design and development process
- No automated contrast checking in CI/CD or design handoff
- Designers/developers may not be aware of contrast requirements or testing tools

## Mitigation Strategies
1. **Immediate Fix**: 
   - Identify specific failing color pairs using accessibility testing tools
   - Adjust lightness/darkness to achieve minimum 4.5:1 contrast for normal text
   - Ensure large text (18pt+ or 14pt bold) meets 3:1 contrast
   - Test both default and dark/light mode variants if applicable
2. **Better Approach**:
   - Establish accessible color palette with predefined compliant combinations
   - Use tools like WebAIM Contrast Checker or axe during development
   - Implement design tokens with accessibility validation
   - Create style guide that documents accessible color usage
3. **Preventive Measures**:
   - Add automated contrast testing to build process
   - Include accessibility checklist in design review
   - Train team on WCAG color contrast requirements
   - Consider using color-blind friendly palettes (like ColorBrewer or Viridis)

## Implementation Plan
1. Use accessibility testing tool (axe, Lighthouse, or WebAIM) to identify specific failing elements
2. Document each failing color pair:
   - Foreground color
   - Background color
   - Current contrast ratio
   - Required adjustment
3. Modify CSS to adjust colors:
   - Option 1: Lighten dark text on dark background
   - Option 2: Darken light text on light background
   - Option 3: Add text shadow or outline for improved legibility
   - Option 4: Change to completely different color combination
4. Verify changes don't break visual design intent
5. Test in both normal and high contrast modes if supported

## Testing Approach
- Automated testing: Run axe or Lighthouse accessibility audit
- Manual testing: 
  - Use browser extensions to simulate color blindness (protanopia, deuteranopia, tritanopia)
  - View in grayscale to check luminance contrast
  - Test with various brightness settings on monitor
  - Verify readability in different lighting conditions (simulate glare, low light)
- Get feedback from users with visual impairments if possible
- Verify that changes don't create new contrast failures elsewhere

## Files to Modify/Create
- Modify: `app/static/css/style.css` (primary stylesheet)
- Modify: `app/static/css/landing.css` (landing page specific)
- Possibly: Create `app/static/css/accessibility.css` for overrides
- Update: Any theme-specific CSS files if dark/light mode implemented

## Dependencies
- Requires accessibility testing tools (free browser extensions available)
- Need to understand current CSS structure and variable usage
- Should check if CSS variables (like `--ink`) are used consistently for easier updates
- May need to adjust multiple instances of same color pattern

## Estimated Effort
- 20-30 minutes to audit and identify specific failures
- 30-45 minutes to implement fixes and test
- Additional time for regression testing to ensure no visual design breaks