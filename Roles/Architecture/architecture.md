# RBAC Role Hierarchy & UI Cleanup — Architecture

## Current Architecture (relevant parts)

```
Request → Flask-Login session → CSRF → Rate limit → @login_required
       → @write_roles_required (role ∈ {admin, manager}) → route → service → repo → sp_*
```

- **RBAC**: `users.role` VARCHAR (admin/manager/viewer); `roles_required(*roles)` decorator → 403
- **Users**: UserProxy wraps RealDictRow; no full_name/department/reporting_manager_id
- **Email**: `Mailer` (SMTP + SendGrid fallback), used by password reset
- **Audit**: `@audit_admin_action` decorator → audit_log
- **Background anim**: auth-bg.js module on ALL pages (base.html:295); canvas #scene in base.html + landing.html
- **3D effects**: dashboard-3d.js (dashboard only) — panel tilt + 3D transforms

---

## Proposed Architecture

### Component Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                         RBAC LAYER                                 │
│  app/security/roles.py                                             │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ ROLE_PERMISSIONS: {job_role: {permission, ...}}  (11 roles)  │  │
│  │ permission_required(perm) — server-side check                │  │
│  │ LEGACY fallback: admin→all, manager→manager set, viewer→read │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────────────┐
│                     ORG HIERARCHY LAYER                            │
│  users.reporting_manager_id (self-FK)                              │
│  UserService: set_reporting_manager (cycle-safe), direct_reports   │
└────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────────────┐
│                     REPORT WORKFLOW LAYER                          │
│  ReportService: submit → notify → inbox → review → status          │
│  reports_workflow blueprint: /team, /reports/submit, /reports/<id> │
│  IDOR: ownership check (submitter OR reporting manager)            │
└────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────────────┐
│                     EXISTING INFRASTRUCTURE (reused)               │
│  Mailer (SMTP/SendGrid) · audit_log · TTLCache · sp_* procedures   │
└────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

### Report Submission Flow
```
Employee (Buyer) → /reports/submit (POST)
    → ReportService.submit_report(payload, user)
        → Validate: title, type, priority
        → reporting_manager_id = user's relationship (AUTO — not user-supplied)
        → INSERT reports (status='submitted')
        → Mailer.send_report_notification(manager_email, ...)  [best-effort]
        → audit_log: report.submitted
    → redirect /team or confirmation

Manager → /team (GET)
    → ReportService.list_team_reports(manager_id, filters)
        → SELECT ... WHERE reporting_manager_id = manager_id  [IDOR-safe by construction]
    → renders My Team + Team Reports inbox

Manager → /reports/<id>/status (PUT)
    → ReportService.update_report_status(id, status, manager)
        → Verify: report.reporting_manager_id == manager.id  [IDOR check]
        → UPDATE status, reviewed_at, review_comment
        → audit_log: report.status_changed
```

### Hierarchy Assignment Flow
```
Admin → /admin/users/edit/<id> (POST)
    → UserService.set_reporting_manager(user_id, manager_id)
        → Reject: user_id == manager_id (self)
        → Reject: manager inactive
        → Cycle check: walk reporting_manager_id chain from manager_id;
          if reaches user_id → reject (would create loop)
        → UPDATE users SET reporting_manager_id
        → audit_log: admin.user.reporting_manager_changed
```

---

## Database Schema

```sql
-- Roles (11 hierarchy roles; supplier documented but NOT seeded)
CREATE TABLE IF NOT EXISTS roles (
    job_role     VARCHAR(40) PRIMARY KEY,
    label        VARCHAR(80) NOT NULL,
    department   VARCHAR(40) NOT NULL,
    description  TEXT,
    sort_order   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS role_permissions (
    job_role     VARCHAR(40) NOT NULL REFERENCES roles(job_role) ON DELETE CASCADE,
    permission   VARCHAR(60) NOT NULL,
    PRIMARY KEY (job_role, permission)
);

-- Users: additive columns (backward compatible)
ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(150);
ALTER TABLE users ADD COLUMN IF NOT EXISTS department VARCHAR(40);
ALTER TABLE users ADD COLUMN IF NOT EXISTS job_role VARCHAR(40);
ALTER TABLE users ADD COLUMN IF NOT EXISTS reporting_manager_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_users_reporting_manager ON users(reporting_manager_id);
CREATE INDEX IF NOT EXISTS idx_users_job_role ON users(job_role);

-- Report/task submissions
CREATE TABLE IF NOT EXISTS reports (
    id                   SERIAL PRIMARY KEY,
    title                VARCHAR(200) NOT NULL,
    report_type          VARCHAR(40) NOT NULL DEFAULT 'general',
    description          TEXT,
    priority             VARCHAR(20) NOT NULL DEFAULT 'medium',
    related_module       VARCHAR(40),
    due_date             DATE,
    status               VARCHAR(20) NOT NULL DEFAULT 'submitted',
    submitted_by         INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    reporting_manager_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    submitted_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    reviewed_at          TIMESTAMP,
    review_comment       TEXT,
    CONSTRAINT reports_priority_chk CHECK (priority IN ('low','medium','high','critical')),
    CONSTRAINT reports_status_chk CHECK (status IN ('draft','submitted','under_review','approved','rejected','completed'))
);

CREATE INDEX IF NOT EXISTS idx_reports_submitted_by ON reports(submitted_by);
CREATE INDEX IF NOT EXISTS idx_reports_manager ON reports(reporting_manager_id);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);
CREATE INDEX IF NOT EXISTS idx_reports_submitted_at ON reports(submitted_at);
```

---

## Permission Model (code-level, fast)

```python
# app/security/roles.py
ROLE_PERMISSIONS = {
    "inventory_director":  {"*"},  # everything
    "vp_operations":       {"inventory.view.all", "dashboard.view", "forecast.view",
                            "analytics.view", "supplier.view", "reports.view.all",
                            "reports.review", "procurement.view", "warehouse.view"},
    "procurement_manager": {"procurement.view", "po.view", "po.create", "po.approve",
                            "supplier.view", "supplier.manage", "reports.review",
                            "report.submit", "dashboard.view"},
    "buyer":               {"po.view", "po.create", "supplier.view",
                            "report.submit", "dashboard.view"},
    "purchasing_clerk":    {"po.view", "po.create", "report.submit", "dashboard.view"},
    "supplier_coordinator":{"supplier.view", "supplier.manage", "report.submit",
                            "dashboard.view"},
    "warehouse_manager":   {"warehouse.view", "stock.receive", "stock.adjust",
                            "reports.review", "report.submit", "dashboard.view"},
    "receiving_clerk":     {"stock.receive", "warehouse.view", "report.submit",
                            "dashboard.view"},
    "inventory_analyst":   {"analytics.view", "forecast.view", "report.submit",
                            "dashboard.view"},
    "forecast_specialist": {"forecast.view", "forecast.run", "forecast.validate",
                            "analytics.view", "report.submit", "dashboard.view"},
    # "supplier": NOT exposed — no external-user support in the security model
}

LEGACY_JOB_ROLE = {"admin": "inventory_director", "manager": "procurement_manager",
                   "viewer": "inventory_analyst"}

def user_permissions(user) -> set[str]:
    job_role = user.get("job_role") or LEGACY_JOB_ROLE.get(user.get("role"), "inventory_analyst")
    perms = ROLE_PERMISSIONS.get(job_role, set())
    if user.get("role") == "admin":
        return {"*"}
    return perms

def permission_required(perm):  # decorator — server-side enforcement
    ...
```

**Key rule:** reporting_manager_id grants VISIBILITY (see subordinate submissions), never permissions.

---

## Security Architecture

| Layer | Enforcement |
|-------|-------------|
| Authentication | `@login_required` (Flask-Login) |
| RBAC permission | `@permission_required("reports.review")` on manager endpoints |
| Resource ownership | Service-level: `report.reporting_manager_id == manager.id` else 404 |
| Hierarchy modify | `@roles_required("admin")` only |
| IDOR | By-construction (manager query filters by reporting_manager_id) + explicit check on detail/status |
| Self-promotion | Role changes admin-only (existing); reporting manager admin-only (new) |

---

## UI Architecture

### New Pages
| Page | Route | Access | Content |
|------|-------|--------|---------|
| My Team + Team Reports | `/team` | permission: reports.review | Direct reports table + report inbox with filters |
| Submit Report | `/reports/submit` | any authenticated | Form; reporting manager auto-populated (read-only) |
| Report Detail | `/reports/<id>` | submitter or manager | Full detail + review actions (manager) |

### Nav (base.html)
- Managers (reports.review permission): "My Team" link
- All users: "Submit Report" link

### Dashboard Layout — NO CHANGE
Verified already paired per spec rows 1-4; reorder queue + warehouse profile stay full-width.

### 3D/Animation Cleanup
- `dashboard-3d.js`: remove panel tilt + rotateX/rotateY transforms; keep opacity/translate fades + SVG draw
- `auth-bg.js`: `if (isNonLanding) { hide canvas; skip init }` — landing + auth pages keep animation
- Version bumps in base.html + dashboard.html

---

## Testing Architecture

```
tests/
├── test_rbac_hierarchy.py      # 11 roles, permissions, decorator, legacy fallback
├── test_reporting_hierarchy.py # self-ref, cycles, direct reports, admin-only
└── test_report_workflow.py     # submit, inbox, IDOR, status, email stub
```

---

## Backward Compatibility

| Aspect | Guarantee |
|--------|-----------|
| `users.role` | Untouched — all existing checks work |
| Existing routes | Unchanged — new decorator is additive |
| Existing users | Migration defaults job_role from legacy role |
| Landing animation | Preserved (guard by .app-shell presence) |
| Dashboard data/APIs | Unchanged (layout already correct) |