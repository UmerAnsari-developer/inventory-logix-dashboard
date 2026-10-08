# RBAC Role Hierarchy & UI Cleanup — Research Report

## 1. Current State (Verified from Codebase)

### Users Table (DB)
Columns: `id, username, email, password_hash, role, is_active, last_login, created_at, oauth_provider, oauth_id, deleted_at`
- **NO** `full_name`, `department`, `reporting_manager_id` columns
- `role` VARCHAR(20) with CHECK `IN ('admin','manager','viewer')` — 3 flat roles

### RBAC Implementation
- `app/security/roles.py`: `WRITE_ROLES = ("admin", "manager")`, `roles_required(*roles)` decorator (403 on mismatch), `write_roles_required` wrapper
- Route protection: `@login_required` + `@write_roles_required` / `@roles_required("admin")`
- No permission strings, no role hierarchy, no resource-level ACLs

### User Management UI (exists)
- `app/routes/admin/user_management_routes.py` — `/admin/users` (admin only): list/create/edit (role, is_active)
- Audit via `@audit_admin_action` decorator
- Templates: `admin/user_management/index.html`, `create.html`, `edit.html`

### Dashboard Layout (VERIFIED — already paired as spec requires)
| Spec Row | Panels | Current State |
|----------|--------|---------------|
| Row 1: Stock Movement + Inventory Mix | ✓ | Already paired (`dashboard-grid` section) |
| Row 2: Slow-moving + Top Demand | ✓ | Already paired |
| Row 3: Top Sales + Top Suppliers | ✓ | Already paired |
| Row 4: Stock Turnover + ABC Analysis | ✓ | Already paired |
| (extra) Reorder queue | full-width | Preserved |
| (extra) Warehouse profile | full-width | Preserved |

**Conclusion: dashboard layout needs NO changes** — the requested arrangement already exists. Responsive grid (`dashboard-grid`) handles stacking.

### 3D Hover Effects (to remove)
`app/static/js/dashboard-3d.js` (120 lines, included only on dashboard via `dashboard.html:525`):
1. **Panel tilt on hover** (lines 8-29): `mousemove` → `perspective(800px) rotateY(±6deg) rotateX(∓6deg) scale(1.008)` + dynamic box-shadow — **THE 3D hover effect to remove**
2. SVG chart entrance (lines 31-62): stroke-dash draw + `scaleY` — non-3D fade/draw (keep or simplify)
3. Inventory mix bars (lines 64-78): `scaleX(0) rotateX(40deg)` → `rotateX(0)` — **3D transform to remove** (keep scaleX fade)
4. Warehouse chart canvas (lines 80-96): `perspective(600px) rotateX(15deg)` — **3D transform to remove**
5. Table rows stagger (lines 98-119): `translateX(-12px) rotateY(4deg)` — **3D transform to remove** (keep translateX fade)

Tooltips/hover-highlighting/click/zoom are CSS/Chart.js-native — unaffected.

### Background Animation (to remove from app pages, KEEP landing)
- `app/static/js/auth-bg.js` (447 lines, Three.js wave + particles) — included on **ALL pages** via `base.html:295` (module script)
- Canvas `#scene` + `#dim` in `base.html:54-55` (app shell + auth pages) AND `landing.html:25-26`
- Existing guard: `isNonLanding = !isLanding && !!document.querySelector('.app-shell')` — currently only disables on **mobile** (line 97: `if (isNonLanding && isMobile)`)
- `isLanding = !!document.getElementById('hero')` (landing has hero)
- **Fix: skip init entirely when `isNonLanding` (any device)** → app pages lose animation; landing + auth pages (no `.app-shell`) keep it
- Landing page animation MUST be preserved (spec §21)

### Email Infrastructure (reuse — do not duplicate)
- `app/services/mailer.py`: `Mailer` class — SMTP (smtplib) + SendGrid HTTPS fallback; `send_password_reset()` with HTML body + CID logo
- Config: `SMTP_HOST/PORT/USERNAME/PASSWORD`, `MAIL_FROM`, `SENDGRID_API_KEY`
- **Add**: `send_report_notification()` reusing the same transport/config pattern

### Audit Logging (integrate — do not duplicate)
- `app/security/audit.py`: `audit_admin_action` decorator + `audit_repo`
- Integrate report/hierarchy actions with existing audit

---

## 2. Legacy Role Mapping Strategy (spec §5)

**Do NOT delete existing roles.** Backward-compatible approach:
- Keep `users.role` (admin/manager/viewer) as the **coarse permission tier** — all existing `current_user.role` checks keep working
- ADD `users.job_role` VARCHAR — the 11 hierarchy roles (organizational identity + fine-grained permissions)
- ADD `role_permissions` table (job_role → permission) for UI display + future DB-driven checks
- Code-level `ROLE_PERMISSIONS` map in `roles.py` for fast checks (no DB round-trip per request)

**Mapping:**
| Legacy | → job_role (default) | Rationale |
|--------|---------------------|-----------|
| admin | `inventory_director` | Full capability incl. system admin |
| manager | `procurement_manager` | Default; admin can change to warehouse_manager |
| viewer | `inventory_analyst` | Read-only analytics role |

---

## 3. Target Role Structure (11 roles, spec §4)

| # | job_role | Department | Key Permissions |
|---|----------|------------|-----------------|
| 1 | inventory_director | Leadership | org-wide, user/role/hierarchy mgmt, system.admin |
| 2 | vp_operations | Leadership | org-wide visibility, analytics, reports.review (NO system.admin) |
| 3 | procurement_manager | Procurement | procurement.view, po.view/approve, supplier.view, reports.review |
| 4 | buyer | Procurement | po.view/create, supplier.view, report.submit |
| 5 | purchasing_clerk | Procurement | po.view/create (data entry), report.submit |
| 6 | supplier_coordinator | Procurement | supplier.view/manage, report.submit |
| 7 | warehouse_manager | Warehouse | warehouse.view, stock.receive/adjust, reports.review |
| 8 | receiving_clerk | Warehouse | stock.receive, warehouse.view, report.submit |
| 9 | inventory_analyst | Analytics | analytics.view, forecast.view, report.submit |
| 10 | forecast_specialist | Analytics | forecast.view/run/validate, analytics.view, report.submit |
| 11 | supplier | External | **NOT exposed** — app has no external-user support; documented, not seeded |

**Inventory Analyst = ONE role** (appears under Analytics only — no duplicate).
**Supplier role = NOT exposed** (no external accounts in the security model; documented only).

---

## 4. Reporting Hierarchy (spec §7-8)

- `users.reporting_manager_id` — self-referencing FK → users(id)
- Safeguards: no self-reference, no cycles (A→B→C→A rejected), only admins modify, managers see direct reports
- Manager visibility: direct reports + subordinate report submissions (RBAC still applies)

---

## 5. Report/Task Submission Workflow (spec §11-15)

New `reports` table: title, report_type, description, priority, related_module, due_date, status (draft/submitted/under_review/approved/rejected/completed), submitted_by, reporting_manager_id, submitted_at, reviewed_at, review_comment.

Flow: Employee submits → DB record + email to manager → Manager inbox (Team Reports) → review/status change.

---

## 6. Security Requirements (spec §16-17)

- Server-side enforcement: auth + RBAC permission + resource ownership
- IDOR: `GET /reports/<id>` must verify ownership (submitter or reporting manager) — never trust IDs
- Subordinates cannot: read/modify others' reports, change own manager, self-promote, access manager pages
- Never rely on frontend hiding

---

## 7. Risks

| Risk | Mitigation |
|------|------------|
| Breaking existing role checks | Keep `users.role` untouched; additive columns only |
| Circular hierarchy | Cycle detection on assignment (walk up the chain) |
| Background-anim removal breaks landing | Guard by `isNonLanding` (landing has no `.app-shell`) |
| 3D removal breaks tooltips | Only remove transform/tilt; keep CSS hover/Chart.js tooltips |
| Email failures | Mailer returns False; workflow continues (email is best-effort) |
| IDOR on reports | Ownership check server-side + tests |

---

## 8. Research Sources

- `app/models.py`, `app/security/roles.py` — RBAC implementation
- `app/routes/admin/user_management_routes.py` — user management UI
- `app/templates/dashboard.html` — layout (verified paired)
- `app/static/js/dashboard-3d.js` — 3D effects inventory
- `app/static/js/auth-bg.js` + `base.html` — background animation wiring
- `app/services/mailer.py` — email infrastructure
- `app/security/audit.py` — audit integration point