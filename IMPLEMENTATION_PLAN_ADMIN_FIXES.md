# Implementation Plan: InventoryLogix Admin Page Security & Reliability Fixes (No Celery/Redis/Docker)

## Overview

This plan addresses all 34 issues identified in the deep production audit of the InventoryLogix Admin Page (`/admin/*` routes). **Constraints: No Celery, no Redis, no Docker.** Uses existing patterns: PostgreSQL for shared state, Python threading for background jobs (like ETL), pure-Python cryptography for encryption.

---

## Batch 1: Critical Security Fixes (Week 1-2)
**Priority:** CRITICAL/HIGH | **Team:** backend-lead + tdd-guide | **Parallelizable:** Yes (independent fixes)

### Issues in Batch 1
| ID | Issue | Severity | Effort |
|----|-------|----------|--------|
| C-001 | Missing CSRF on destructive admin forms | CRITICAL | Low |
| C-002 | Admin self-demotion/deletion possible | CRITICAL | Low |
| C-003 | No rate limiting on admin write endpoints | CRITICAL | Low |
| C-004 | Sensitive config values exposed in dashboard | CRITICAL | Low |
| H-001 | Password reset token exposed in UI (dev fallback) | HIGH | Low |
| M-003 | System config override no validation | MEDIUM | Low |
| M-008 | No admin session timeout enforcement | MEDIUM | Low |
| M-009 | No health check/readiness endpoint for admin | MEDIUM | Low |
| L-001 | Log viewer path traversal risk | LOW | Low |
| R-003 | Define config key allowlist with types | REC | Low |

### Dependencies
- **None** — all fixes are independent and can run in parallel
- No schema changes required (except C-004 adds `is_sensitive` column)
- No infrastructure changes required

### Files to Modify

#### C-001: CSRF Protection on Destructive Forms
| File | Action |
|------|--------|
| `app/templates/admin/backup/index.html` | Add `csrf_token` hidden input to restore (line 415) and delete (line 425) forms; replace `onclick="return confirm(...)"` with `data-confirm` |
| `app/templates/admin/user_management/index.html` | Add CSRF token to change_role (lines 47-54) and toggle_active (lines 72-80) forms |
| `app/templates/admin/system_config/index.html` | Add CSRF token to delete action form |
| `app/templates/admin/audit_report/index.html` | Add CSRF token to delete action form |
| `app/static/js/main.js` | Verify `data-confirm` handler exists (already implemented per audit) |

#### C-002: Admin Self-Protection Guards
| File | Action |
|------|--------|
| `app/routes/admin/user_management_routes.py` | Add `if user_id == current_user.id:` guards on `/edit` (line ~58), `/toggle` (line ~90), `/change-role` (line ~110) endpoints |

#### C-003: Rate Limiting on Admin Write Endpoints
| File | Action |
|------|--------|
| `app/routes/admin/backup_routes.py` | Add `@limiter.limit("30 per minute")` to all POST endpoints |
| `app/routes/admin/system_config_routes.py` | Add `@limiter.limit("30 per minute")` to all POST endpoints |
| `app/routes/admin/user_management_routes.py` | Add `@limiter.limit("30 per minute")` to all POST endpoints |
| `app/routes/admin/data_import_routes.py` | Add `@limiter.limit("10 per minute")` (stricter for imports) |
| `app/routes/admin/audit_report_routes.py` | Add `@limiter.limit("30 per minute")` to all POST endpoints |

#### C-004: Mask Sensitive Config Values
| File | Action |
|------|--------|
| `app/services/admin_dashboard_service.py` | Lines 82-90: Add masking logic for keys containing `password`, `secret`, `key`, `token`, `api` → return `***` |
| `app/templates/admin/dashboard/index.html` | Lines 124-125: Ensure masked values displayed (no additional change if service masks) |
| `app/database/schema.sql` | Add `is_sensitive BOOLEAN DEFAULT FALSE` column to `system_config_overrides` table |

#### H-001: Password Reset Token in UI
| File | Action |
|------|--------|
| `app/routes/auth.py` | Lines 88-92: Remove `reset_link` from template context; log server-side only |

#### M-003 + R-003: Config Validation Allowlist
| File | Action |
|------|--------|
| `app/routes/admin/system_config_routes.py` | Lines 32-50: Define `ALLOWED_CONFIG_KEYS = {key: type}` dict; validate on create/edit |
| `app/services/system_config_repo.py` | Add validation method using allowlist |

#### M-008: Admin Session Timeout
| File | Action |
|------|--------|
| `app/config/settings.py` | Add `ADMIN_SESSION_TIMEOUT_MINUTES = 30` |
| `app/security/roles.py` | Add `@admin_session_required` decorator that checks session age and forces re-auth for sensitive actions |
| `app/routes/admin/*_routes.py` | Apply decorator to sensitive endpoints (user mgmt, config, backup, import) |

#### M-009: Admin Health Endpoint
| File | Action |
|------|--------|
| `app/routes/admin/dashboard_routes.py` | Add `/admin/health` endpoint checking: DB connectivity, backup disk space, log disk space |
| `app/services/admin_dashboard_service.py` | Add `health_check()` method |

#### L-001: Log Viewer Path Traversal
| File | Action |
|------|--------|
| `app/services/log_viewer_service.py` | Add path validation: `os.path.realpath(log_path).startswith(ALLOWED_LOG_DIR)` |

### Test Strategy (Batch 1)
```bash
# Unit tests
pytest tests/test_admin_csrf.py -v                    # C-001
pytest tests/test_admin_self_protection.py -v         # C-002
pytest tests/test_admin_rate_limits.py -v             # C-003
pytest tests/test_config_masking.py -v                # C-004
pytest tests/test_auth_reset_token.py -v              # H-001
pytest tests/test_config_validation.py -v             # M-003/R-003
pytest tests/test_admin_session_timeout.py -v         # M-008
pytest tests/test_admin_health.py -v                  # M-009
pytest tests/test_log_viewer_path_traversal.py -v     # L-001

# Integration tests
pytest tests/test_admin_routes.py -v                  # All admin routes with new protections

# Coverage target: 85%+ on modified files
```

### Effort Estimate: **~40 hours** (5 days for 1 backend-lead + 1 tdd-guide)

---

## Batch 2: Data Integrity & Audit Infrastructure (Week 2-4)
**Priority:** HIGH | **Team:** backend-lead + tdd-guide | **Parallelizable:** Partially (schema changes block some)

### Issues in Batch 2
| ID | Issue | Severity | Effort |
|----|-------|----------|--------|
| H-002 | In-memory lockout store not shared across workers | HIGH | Medium |
| H-004 | Backup restore no transaction safety | HIGH | Medium |
| H-005 | No audit trail for admin actions | HIGH | Medium |
| H-006 | No soft-delete for critical admin entities | HIGH | Medium |
| H-007 | No backup encryption/integrity verification | HIGH | High |
| H-008 | Data import race condition on SKU conflict | HIGH | Medium |
| M-004 | User activity analytics N+1 query | MEDIUM | Low |
| M-005 | Notification center no pagination | MEDIUM | Low |
| M-006 | Export endpoints no streaming/memory pressure | MEDIUM | Medium |
| M-007 | Audit report generation no timeout/progress | MEDIUM | High |
| MR-001 | Centralized audit decorator | MISSING | Medium |
| MR-002 | Soft-delete on all admin tables | MISSING | Medium |
| MR-003 | Background job queue for long-running ops | MISSING | High |
| MR-004 | Shared state for rate limiting/lockout | MISSING | Medium |
| MR-005 | Admin-specific session timeout + step-up auth | MISSING | Low |

### Dependencies
- **H-006, MR-002 (Soft-delete)** → Requires schema migration → Blocks H-004, H-007 restore logic
- **MR-003 (Background jobs)** → Uses Python threading (existing ETL pattern) → Blocks M-006, M-007, H-004, H-007
- **MR-004 (Shared state)** → Uses PostgreSQL table for rate limit/lockout state → Required for H-002
- **MR-001 (Audit decorator)** → Independent, apply after schema stable

### Files to Modify

#### H-002 + MR-004: PostgreSQL-Backed Rate Limiting & Lockout (No Redis)
| File | Action |
|------|--------|
| `app/database/schema.sql` | Add `rate_limit_state` table: `key VARCHAR PRIMARY KEY, count INT, window_start TIMESTAMP, locked_until TIMESTAMP` |
| `app/services/auth_service.py` | Lines 33-39: Replace `defaultdict` + `threading.Lock` with PostgreSQL-backed limiter using advisory locks |
| `app/extensions.py` | Configure Flask-Limiter with custom PostgreSQL storage backend (implement `RateLimitStorage` interface) |
| `app/config/settings.py` | Keep `RATELIMIT_STORAGE_URI = "memory://"` for single-worker; document multi-worker uses PG backend |

#### H-004: Backup Restore Transaction Safety
| File | Action |
|------|--------|
| `app/services/backup_service.py` | Wrap `restore_backup()` in `BEGIN`/`COMMIT`/`ROLLBACK`; add pre-restore integrity check (checksum) |

#### H-005 + MR-001: Centralized Audit Decorator
| File | Action |
|------|--------|
| `app/security/audit.py` | **NEW FILE**: Create `@audit_action(action_name, entity_type, entity_id)` decorator |
| `app/routes/admin/*_routes.py` | Apply `@audit_action` to ALL write endpoints (create, edit, delete, toggle, import, restore) |
| `app/repositories/audit_repo.py` | Ensure `record()` method handles decorator calls |

#### H-006 + MR-002: Soft-Delete on Admin Tables
| File | Action |
|------|--------|
| `app/database/schema.sql` | Add `deleted_at TIMESTAMP`, `deleted_by INTEGER REFERENCES users(id)` to: `system_backups`, `system_config_overrides`, `scheduled_audit_reports` |
| `app/database/procedures.sql` | Update CRUD procedures for soft-delete (filter `WHERE deleted_at IS NULL`) |
| `app/repositories/system_backup_repo.py` | Update queries to respect soft-delete |
| `app/repositories/system_config_repo.py` | Update queries to respect soft-delete |
| `app/repositories/scheduled_audit_report_repo.py` | Update queries to respect soft-delete |
| `migrations/versions/xxx_add_soft_delete_admin_tables.py` | **NEW**: Alembic migration |

#### H-007: Backup Encryption + Integrity (Pure Python)
| File | Action |
|------|--------|
| `app/services/backup_service.py` | Add AES-256 encryption using `cryptography.fernet.Fernet`; generate SHA-256 checksum; store metadata in `system_backups` |
| `app/database/schema.sql` | Add `encrypted BOOLEAN`, `checksum VARCHAR(64)`, `encryption_key_id VARCHAR(36)` to `system_backups` |
| `app/config/settings.py` | Add `BACKUP_ENCRYPTION_KEY` (from env, base64-encoded 32-byte key) |
| `requirements.txt` | Add `cryptography>=41.0` |

#### H-008: Data Import Race Condition
| File | Action |
|------|--------|
| `app/routes/admin/data_import_routes.py` | Lines 145-153: Use `SELECT ... FOR UPDATE` on SKU before upsert; or add PostgreSQL advisory lock per SKU (`pg_advisory_xact_lock(hashtext(sku))`) |

#### M-004: N+1 Query Fix (User Activity Analytics)
| File | Action |
|------|--------|
| `app/services/user_activity_analytics_service.py` | Replace 4 separate queries with single CTE query |
| `app/routes/admin/user_activity_analytics_routes.py` | Lines 20-23: Call single batched service method |

#### M-005: Notification Center Pagination
| File | Action |
|------|--------|
| `app/services/notification_center_service.py` | Add `limit`, `offset` params to `list_notifications()`; default limit 50 |
| `app/routes/admin/notification_center_routes.py` | Pass pagination params from request |
| `app/templates/admin/notification_center/index.html` | Add pagination controls |

#### M-006 + R-004: Streaming Exports (No Celery)
| File | Action |
|------|--------|
| `app/services/export_service.py` | Replace in-memory CSV with generator yielding chunks; use `Response(stream_with_context(generator), mimetype='text/csv')` |
| `app/routes/admin/export_routes.py` | Update to use streaming response |

#### M-007 + R-005 + MR-003: Async Reports with Progress Polling (Threading-based)
| File | Action |
|------|--------|
| `app/services/audit_report_service.py` | Move `generate_and_save_report()` to background thread (use `threading.Thread` + `queue.Queue` for result, like ETL pattern) |
| `app/routes/admin/audit_report_routes.py` | Line 180: Start background thread, return job ID immediately; add `/admin/audit-reports/progress/<job_id>` polling endpoint |
| `app/services/job_tracker.py` | **NEW FILE**: In-memory job tracker with `threading.Lock` for progress state (job_id → {status, progress, result, error}) |
| `app/templates/admin/audit_report/index.html` | Add progress bar polling UI (JavaScript fetch to progress endpoint) |

### Test Strategy (Batch 2)
```bash
# Schema migration tests
pytest tests/test_migrations.py::test_soft_delete_admin_tables -v

# PostgreSQL-backed rate limiting tests
pytest tests/test_pg_rate_limiting.py -v          # H-002, MR-004

# Threading-based background job tests
pytest tests/test_threaded_jobs.py -v              # MR-003, M-007

# Unit tests
pytest tests/test_backup_restore_transaction.py -v   # H-004
pytest tests/test_audit_decorator.py -v              # H-005, MR-001
pytest tests/test_backup_encryption.py -v            # H-007
pytest tests/test_data_import_race_condition.py -v   # H-008
pytest tests/test_user_activity_n1_query.py -v       # M-004
pytest tests/test_notification_pagination.py -v      # M-005
pytest tests/test_streaming_exports.py -v            # M-006, R-004
pytest tests/test_async_reports_progress.py -v       # M-007, R-005

# Integration tests
pytest tests/test_admin_audit_trail.py -v            # Full audit trail
pytest tests/test_admin_soft_delete.py -v            # Soft-delete recovery
```

### Effort Estimate: **~100 hours** (2.5 weeks for 2 backend-leads + 1 tdd-guide)

---

## Batch 3: UX Polish & Remaining Recommendations (Week 3-4, parallel with Batch 2)
**Priority:** MEDIUM/LOW/REC | **Team:** frontend-lead + tdd-guide | **Parallelizable:** Yes (mostly template/JS changes)

### Issues in Batch 3
| ID | Issue | Severity | Effort |
|----|-------|----------|--------|
| M-001 | Log viewer no pagination UI | MEDIUM | Low |
| M-002 | User activity analytics chart null guard | MEDIUM | Low |
| R-001 | Add preview/confirm step for data import | REC | Medium |
| R-002 | Add pagination to all large-list admin pages | REC | Low |
| L-002 | Admin menu hidden from non-admins only in UI | LOW | Low |

### Dependencies
- **R-001 (Import preview)** → Depends on H-003 (data import preview) from Batch 1
- **M-001, R-002 (Pagination)** → Can use same pagination component pattern
- **L-002** → Already has RBAC on routes; just defense-in-depth

### Files to Modify

#### M-001: Log Viewer Pagination
| File | Action |
|------|--------|
| `app/templates/admin/log_viewer/index.html` | Add pagination links preserving filter params (page, level, search) |
| `app/routes/admin/log_viewer_routes.py` | Ensure `limit`/`offset` passed to service |

#### M-002: Chart Null Guard
| File | Action |
|------|--------|
| `app/templates/admin/user_activity_analytics/index.html` | Add `if (chartCanvas && chartCanvas.getContext)` guard before chart init |

#### R-001: Data Import Preview/Confirm
| File | Action |
|------|--------|
| `app/routes/admin/data_import_routes.py` | Add `/preview` endpoint: parse CSV, show row count, conflicts (SKU matches), sample rows |
| `app/templates/admin/data_import/index.html` | Two-step UI: upload → preview → confirm → commit |
| `app/services/data_import_service.py` | **NEW**: `preview_import(csv_content)` method |

#### R-002: Pagination on All Large Lists
| File | Action |
|------|--------|
| `app/templates/admin/user_activity/index.html` | Add pagination (reuses pattern from log viewer) |
| `app/templates/admin/user_activity_analytics/index.html` | Add pagination if large datasets |
| `app/templates/admin/backup/index.html` | Add pagination for backup list |
| `app/templates/admin/audit_report/index.html` | Add pagination for report list |

#### L-002: Admin Menu Defense-in-Depth
| File | Action |
|------|--------|
| `app/templates/base.html` | Add server-side check in nav partial (already has RBAC on routes, this is belt-and-suspenders) |

### Test Strategy (Batch 3)
```bash
# Frontend/UX tests
pytest tests/test_frontend_mitigations.py -v           # M-002, pagination UI
pytest tests/test_admin_pagination.py -v               # M-001, R-002
pytest tests/test_data_import_preview.py -v            # R-001

# E2E tests (Playwright)
pytest tests/e2e/test_admin_import_flow.py -v          # Full import preview→confirm
pytest tests/e2e/test_admin_pagination.py -v           # All paginated pages

# Visual regression (optional)
pytest tests/visual/test_admin_pages.py -v
```

### Effort Estimate: **~32 hours** (4 days for 1 frontend-lead + 1 tdd-guide)

---

## Cross-Batch Dependencies Summary

```
Batch 1 (Week 1-2)          Batch 2 (Week 2-4)           Batch 3 (Week 3-4)
├── C-001 CSRF              ├── H-002 PG rate limiting   ├── M-001 Log pagination
├── C-002 Self-protect      ├── H-004 Backup txn         ├── M-002 Chart null guard
├── C-003 Rate limits       ├── H-005 Audit decorator    ├── R-001 Import preview ← needs H-003
├── C-004 Config masking    ├── H-006 Soft-delete ──────┐
├── H-001 Reset token       ├── H-007 Backup encrypt ───┤  (schema migration)
├── M-003 Config validation ├── H-008 Import race       │
├── M-008 Admin timeout     ├── M-004 N+1 query         │
├── M-009 Health endpoint   ├── M-005 Notif pagination  │
├── L-001 Path traversal    ├── M-006 Streaming export  │
└── R-003 Config allowlist  ├── M-007 Async reports ────┘     (threading-based)
                              ├── MR-001 Audit decorator
                              ├── MR-002 Soft-delete
                              ├── MR-003 Background jobs (threading)
                              ├── MR-004 PG shared state
                              └── MR-005 Admin timeout
```

---

## Overall Timeline

| Week | Batch 1 | Batch 2 | Batch 3 |
|------|---------|---------|---------|
| 1    | ████████ |         |         |
| 2    | ████████ | ████    |         |
| 3    |         | ████████ | ████████ |
| 4    |         | ████████ | ████████ |

**Total Effort: ~172 hours** (4 weeks with 3 parallel tracks)

---

## Rollback Plan

| Batch | Database Rollback | Code Rollback | Config Rollback |
|-------|-------------------|---------------|-----------------|
| 1     | `alembic downgrade -1` (if schema changed) | `git revert <commit>` | Remove `ADMIN_SESSION_TIMEOUT_MINUTES` |
| 2     | `alembic downgrade -1` (soft-delete migration) | `git revert <commit>` | Remove `BACKUP_ENCRYPTION_KEY` |
| 3     | None (template/JS only) | `git revert <commit>` | None |

---

## Success Criteria (All Batches)

- [ ] All unit tests pass (pytest coverage ≥ 85% on modified files)
- [ ] All integration tests pass
- [ ] All E2E tests pass for critical admin flows
- [ ] Security review passes (no CRITICAL/HIGH issues remain)
- [ ] Performance benchmarks: admin dashboard < 500ms, exports stream without OOM
- [ ] Documentation updated: `ADMIN_SECURITY.md`, `ADMIN_OPERATIONS.md`
- [ ] Manual verification completed with demo credentials (admin/Admin@123)

---

## Agent Assignment

| Agent | Batch | Primary Responsibility |
|-------|-------|------------------------|
| backend-lead-1 | 1 | C-001, C-002, C-003, C-004, H-001, M-003, M-008, M-009, L-001, R-003 |
| tdd-guide-1 | 1 | Write tests first for all Batch 1 issues |
| backend-lead-2 | 2 | H-002, H-004, H-005, H-006, H-007, H-008, M-004, M-005, M-006, M-007, MR-001-005 |
| tdd-guide-2 | 2 | Write tests first for all Batch 2 issues |
| frontend-lead | 3 | M-001, M-002, R-001, R-002, L-002 |
| tdd-guide-3 | 3 | Write tests first for all Batch 3 issues |

---

## Notes for Agents

1. **TDD Workflow Mandatory**: Write failing test → Implement fix → Verify pass → Refactor
2. **Security First**: All CRITICAL fixes (Batch 1) must be deployed before any feature work
3. **Schema Changes**: Run migrations in staging first; verify rollback works
4. **No Redis/Celery**: Use PostgreSQL for shared state, Python threading for background jobs (see `app/database/etl.py` for pattern)
5. **Asset Versioning**: Bump `?v=X.Y` in `base.html` for any CSS/JS changes
6. **Session Behavior**: Remember — sessions end on browser close (no persistent remember cookie)
7. **Encryption**: Use `cryptography.fernet.Fernet` (pure Python, no native deps) for backup encryption