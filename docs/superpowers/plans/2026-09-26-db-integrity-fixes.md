# Database Integrity Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 68 database integrity issues identified in the audit report across 5 batches, ensuring data consistency, security, and performance.

**Architecture:** The fixes span database schema (DDL), stored procedures (PL/pgSQL), Python services/repositories, Flask routes, and tests. Changes are grouped by dependency order: schema → procedures → services → routes → tests.

**Tech Stack:** PostgreSQL 15+, Flask 3.x, SQLAlchemy (core only), psycopg2, pytest, Alembic migrations.

**Spec:** This plan implements the 68 issues from the audit report (DB-001 through DB-088, with some duplicates noted).

---

## Global Constraints

- All SQL uses parameterized queries via stored procedures (`sp_*` functions)
- CSP nonces generated per-request for inline scripts + import maps
- Role-based access: `viewer` (read-only), `admin`/`manager` (write)
- Rate limits: auth (10/min login, 5/min register), API writes (30/min), movements (60/min)
- Sessions end when browser closes (no persistent remember cookie)
- All endpoints return consistent JSON envelope: `{success: boolean, data: ..., error: ...}`
- Asset version query params (`style.css?v=20.3`, `main.js?v=1.2`, `ai-features.js?v=9.2`) must be bumped on every JS/CSS change
- Do NOT add wheel-hijacking smooth-scroll library (Lenis etc.)

---

## Review Focus

1. **Concurrent stock movements** — Two simultaneous OUT movements for the same product must not both succeed if stock is insufficient. The row lock in `sp_movement_record` must serialize them.
2. **SKU uniqueness** — Creating a product with an existing SKU must return 422 (not 500). The partial unique index `products_sku_live_key` must allow reusing deleted SKUs.
3. **PO state machine** — Invalid transitions (draft→received, received→approved) must be rejected with 422. Receiving a PO must create a movement ledger row via `sp_movement_record`.
4. **Soft delete referential integrity** — Deleting a supplier/product must not cascade-delete movements, POs, or audit rows. `deleted_at` filters must apply everywhere.
5. **ETL watermark correctness** — Incremental ETL must use `max(created_at)` of processed rows, not `NOW()`, to avoid skipping late-committed rows.

---

## Batch 1: Critical/High (17 Issues)

### Task 1: DB-002 — Movement TOCTOU: Atomic `sp_movement_record` ✅ ALREADY DONE

**Status:** Already implemented in `procedures.sql:225-268`. The function uses `SELECT ... FOR UPDATE` to lock the product row, validates stock, inserts movement, and updates stock in a single transaction.

**Files to verify:**
- `app/database/procedures.sql:225-268` — `sp_movement_record` implementation
- `tests/test_db_integrity_fixes.py:63-117` — `test_d1_concurrent_out_movements_cannot_go_negative`

**Validation:** Run `pytest tests/test_db_integrity_fixes.py::test_d1_concurrent_out_movements_cannot_go_negative -v`

---

### Task 2: DB-003 — PO on_order/stock Reconciliation ✅ ALREADY DONE

**Status:** Already implemented in `procedures.sql:662-699` (`sp_po_transition`). The function handles stock/on_order effects atomically with the state transition.

**Files to verify:**
- `app/database/procedures.sql:662-699` — `sp_po_transition` implementation
- `tests/test_db_integrity_fixes.py:178-214` — `test_d3_po_receive_applies_stock_once`
- `tests/test_db_integrity_fixes.py:217-245` — `test_d4_invalid_po_transition_rejected`

**Validation:** Run `pytest tests/test_db_integrity_fixes.py::test_d3_po_receive_applies_stock_once tests/test_db_integrity_fixes.py::test_d4_invalid_po_transition_rejected -v`

---

### Task 3: DB-001 — SKU Unique Violation → 500 (Error Translation)

**Files to modify:**
- `app/services/product_service.py:86-99` — `create()` method already catches `UniqueViolation` and raises `ProductError`
- `app/repositories/product_repo.py:72-87` — `create()` calls `sp_product_create`
- `app/routes/api.py:175-189` — `create_product()` endpoint catches `Exception` and returns 422

**Changes needed:**
1. Verify `ProductService.create()` properly translates `UniqueViolation` to `ProductError` (line 93-98)
2. Ensure `api.py:183-184` catches `ProductError` specifically, not generic `Exception`
3. Add test for race condition backstop (already in `test_db_integrity_fixes.py:154-171`)

**Migration required:** No (partial unique index `products_sku_live_key` exists in `schema.sql:97-117`)

**Test updates:** Verify existing test `test_d2_service_race_backstop_maps_unique_violation` passes

**Dependencies:** None

**Risk:** Low — error translation already implemented, just needs verification

---

### Task 4: DB-009 — PO Number Unique Violation → 500 (Error Translation)

**Files to modify:**
- `app/repositories/po_repo.py:24-44` — `create()` already catches `UniqueViolation` and raises `POError`
- `app/routes/api.py` — Need to add PO creation endpoint if missing, or verify existing one

**Changes needed:**
1. Verify `PurchaseOrderRepository.create()` properly translates `UniqueViolation` to `POError` (line 39-43)
2. Check if PO creation endpoint exists in `api.py` or admin routes
3. If missing, add PO creation endpoint with proper error handling

**Migration required:** No (PO number unique constraint exists in `schema.sql:121`)

**Test updates:** Add test for PO number duplicate handling

**Dependencies:** None

**Risk:** Low — pattern already established for products

---

### Task 5: DB-004 — Supplier Soft Delete + Collapse `sp_product_delete` ✅ ALREADY DONE

**Status:** Already implemented:
- `procedures.sql:209-216` — `sp_supplier_delete` sets `deleted_at`
- `procedures.sql:771-778` — `sp_product_delete` sets `deleted_at`
- `schema.sql:24, 40, 61` — `deleted_at` columns on users, suppliers, products
- All list/find procedures filter `WHERE deleted_at IS NULL`

**Files to verify:**
- `app/database/procedures.sql:209-216, 771-778`
- `app/database/schema.sql:24, 40, 61`
- `tests/test_db_integrity_fixes.py:252-287` — `test_d5_supplier_soft_delete`

**Validation:** Run `pytest tests/test_db_integrity_fixes.py::test_d5_supplier_soft_delete -v`

---

### Task 6: DB-021 — Product Edit Bypass (Remove `current_stock` from UPDATE)

**Files to modify:**
- `app/database/procedures.sql:80-99` — `sp_product_update` already has comment "DB-021: current_stock is intentionally NOT updated here" and excludes it from UPDATE
- `app/repositories/product_repo.py:90-103` — `update()` passes `current_stock` parameter but procedure ignores it
- `app/services/product_service.py:61-65` — `validate_payload()` only includes `current_stock` if explicitly provided

**Changes needed:**
1. Verify `sp_product_update` does NOT update `current_stock` (already correct)
2. Remove `current_stock` parameter from `sp_product_update` signature entirely (cleanup)
3. Update `ProductRepository.update()` to not pass `current_stock`
4. Update `ProductService.validate_payload()` to reject `current_stock` in update payloads

**Migration required:** No (procedure change only)

**Test updates:** Add test that PUT /api/products/<id> with current_stock is rejected or ignored

**Dependencies:** None

**Risk:** Low — already enforced at procedure level

---

### Task 7: DB-024 — PO Receive → Ledger Row (`sp_po_transition` calls `sp_movement_record`) ✅ ALREADY DONE

**Status:** Already implemented in `procedures.sql:682-689`. On `received` status, calls `sp_movement_record` for IN movement.

**Files to verify:**
- `app/database/procedures.sql:682-689`
- `tests/test_db_integrity_fixes.py:178-214` — verifies stock increase and movement row creation

**Validation:** Run existing test

---

### Task 8: DB-025 — Mark-Ordered Creates Real PO (Single Txn)

**Files to modify:**
- `app/services/product_service.py` or new `po_service.py` — Need a "mark ordered" function that creates PO in single transaction
- `app/repositories/po_repo.py` — Add method for atomic PO creation with initial status

**Changes needed:**
1. Create `POService.mark_ordered(product_id, supplier_id, quantity, unit_cost)` that:
   - Generates PO number
   - Creates PO with status 'approved' or 'in_transit' in single transaction
   - Updates product `on_order` atomically
2. Add repository method `create_and_approve()` or similar
3. Add API endpoint `/api/products/<id>/mark-ordered`

**Migration required:** No (uses existing tables/procedures)

**Test updates:** Add test for atomic mark-ordered operation

**Dependencies:** DB-003 (PO transition), DB-024 (PO receive)

**Risk:** Medium — new business logic, needs careful transaction handling

---

### Task 9: DB-026 — PO Create Status Whitelist

**Files to modify:**
- `app/database/procedures.sql:638-651` — `sp_po_create` accepts any status, should validate
- `app/repositories/po_repo.py:24-44` — `create()` passes status directly

**Changes needed:**
1. Add CHECK constraint or validation in `sp_po_create` to only allow 'draft' on create
2. Update `PurchaseOrderRepository.create()` to enforce 'draft' status
3. Update `ProductService`/`POService` to only create draft POs

**Migration required:** Yes — add CHECK constraint to `purchase_orders.status` or validate in procedure

**Test updates:** Add test that PO create with non-draft status fails

**Dependencies:** None

**Risk:** Low — simple validation addition

---

### Task 10: DB-027 — Auto-Draft PO Single Txn + Catch POError

**Files to modify:**
- `app/services/po_service.py` (new) or `product_service.py` — Auto-draft PO creation
- `app/repositories/po_repo.py` — Ensure `create()` wraps in transaction

**Changes needed:**
1. Create `POService.create_draft_po()` that generates PO number, creates PO in single transaction
2. Catch `POError` (unique violation) and retry with new PO number
3. Add API endpoint for auto-draft PO creation

**Migration required:** No

**Test updates:** Add test for auto-draft PO with collision retry

**Dependencies:** DB-009 (PO number unique error translation)

**Risk:** Medium — retry logic for unique collisions

---

### Task 11: DB-022 — Alembic Collision (Guard `op.create_table`)

**Files to modify:**
- `migrations/env.py` or migration scripts — Add `if_not_exists` guards
- All migration files in `migrations/versions/`

**Changes needed:**
1. Update migration template in `migrate.py:31-54` to include `if_not_exists` pattern
2. For existing migrations, add guards where tables might already exist
3. Use `op.get_bind().dialect.has_table()` checks before `op.create_table()`

**Migration required:** Yes — modify existing migrations or create new ones with guards

**Test updates:** Test migration upgrade/downgrade on fresh and existing DB

**Dependencies:** None

**Risk:** Medium — modifying migration history can be tricky

---

### Task 12: DB-023 — `migrate.py` Password Leak

**Files to modify:**
- `migrate.py:60-70` — `apply_upgrade()` prints stderr which may contain password
- `migrate.py:73-83` — `apply_downgrade()` same issue

**Changes needed:**
1. Sanitize subprocess output before printing (remove DSN/password)
2. Use `psycopg2` connection params without password in logs
3. Mask `DATABASE_URL` in any error output

**Migration required:** No

**Test updates:** Add test that verifies no password in migration output

**Dependencies:** None

**Risk:** Low — simple output sanitization

---

### Task 13: DB-028 — ETL Watermark Fix (Max `created_at`) ✅ ALREADY DONE

**Status:** Already implemented in `etl_procedures.sql:208-253` (`etl_load_login_events`), `etl_load_session_events`, `etl_load_signup_events`. Uses `MAX(created_at)` of processed rows.

**Files to verify:**
- `app/database/etl_procedures.sql:208-253, 260-304, 309-353`
- `app/database/etl.py:520-530` — Python ETL also uses watermark

**Validation:** Run ETL tests

---

### Task 14: DB-029 — Health Check DB Ping

**Files to modify:**
- `app/routes/api.py:31-44` — `/api/health` endpoint already does `SELECT 1`
- `app/database/connection.py:213-220` — `_validate_connection()` does `SELECT 1`

**Changes needed:**
1. Verify health check uses lightweight query
2. Consider removing per-request ping (DB-039/DB-052 already removed it from connection checkout)
3. Ensure health check doesn't create new connection pool exhaustion

**Migration required:** No

**Test updates:** Verify health check works under load

**Dependencies:** DB-039 (pool churn fix)

**Risk:** Low — already implemented

---

### Task 15: DB-030 — Fail Closed on Unknown `FLASK_ENV`

**Files to modify:**
- `app/config/settings.py:142-149` — `get_config()` already raises `RuntimeError` for unknown env

**Changes needed:**
1. Verify `get_config()` fails fast on unknown `FLASK_ENV` (already does)
2. Ensure production deployment sets `FLASK_ENV=production` explicitly

**Migration required:** No

**Test updates:** Add test for unknown FLASK_ENV

**Dependencies:** None

**Risk:** Low — already implemented

---

### Task 16: DB-031 — `pg_restore` Security Fixes

**Files to modify:**
- `app/database/connection.py` or backup/restore scripts
- `app/services/backup_service.py`

**Changes needed:**
1. Review `pg_restore` usage in backup/restore functionality
2. Ensure `--no-owner --no-privileges` flags used
3. Validate restored data doesn't escalate privileges

**Migration required:** No

**Test updates:** Add backup/restore security test

**Dependencies:** None

**Risk:** Medium — requires understanding of backup/restore flow

---

### Task 17: DB-032 — Render Blueprint Name Match

**Files to modify:**
- `render.yaml` (if exists) or deployment configs
- `app/__init__.py` — App factory name

**Changes needed:**
1. Verify Render blueprint service name matches Flask app name
2. Ensure `DATABASE_URL` wiring is correct in Render config

**Migration required:** No

**Test updates:** Deployment verification

**Dependencies:** None

**Risk:** Low — configuration only

---

### Task 18: DB-033 — CSV Import Fixes

**Files to modify:**
- `app/routes/admin/data_import_routes.py`
- `app/services/data_import_service.py`

**Changes needed:**
1. Fix CSV import to use parameterized queries
2. Add validation for required columns
3. Handle duplicate SKU gracefully (upsert or skip)
4. Transaction per row or batch with savepoints

**Migration required:** No

**Test updates:** Add CSV import tests

**Dependencies:** DB-001 (SKU unique handling)

**Risk:** Medium — data import is complex

---

### Task 19: DB-034 — Warehouse/ETL Re-apply Migration

**Files to modify:**
- `migrations/versions/20260925_db_integrity_fixes.py` or similar
- `app/database/schema.sql` — Warehouse tables already defined

**Changes needed:**
1. Create migration to re-apply warehouse/ETL schema changes
2. Ensure idempotent (IF NOT EXISTS guards)
3. Run ETL after migration

**Migration required:** Yes — new migration file

**Test updates:** Test migration on fresh and existing DB

**Dependencies:** DB-022 (Alembic collision guards)

**Risk:** Medium — schema migration

---

## Batch 2: Schema/Constraints (11 Issues)

### Task 20: DB-035 — FK CASCADE→RESTRICT (Movements)

**Files to modify:**
- `app/database/schema.sql:65` — `movements.product_id REFERENCES products(id) ON DELETE RESTRICT` (already RESTRICT)
- `app/database/schema.sql:70` — `movements.user_id REFERENCES users(id) ON DELETE RESTRICT` (already RESTRICT)

**Changes needed:**
1. Verify current FKs are RESTRICT (they are)
2. No change needed if already correct

**Migration required:** No (already correct)

**Test updates:** Verify FK behavior in tests

**Dependencies:** None

**Risk:** None — already correct

---

### Task 21: DB-036 — FK SET NULL→RESTRICT (Audit Log, Purchase Orders)

**Files to modify:**
- `app/database/schema.sql:159` — `audit_log.user_id REFERENCES users(id) ON DELETE RESTRICT` (already RESTRICT)
- `app/database/schema.sql:122` — `purchase_orders.supplier_id REFERENCES suppliers(id) ON DELETE RESTRICT` (already RESTRICT)
- `app/database/schema.sql:123` — `purchase_orders.product_id REFERENCES products(id) ON DELETE RESTRICT` (already RESTRICT)

**Changes needed:**
1. Verify all FKs are RESTRICT (they are)
2. No change needed

**Migration required:** No (already correct)

**Test updates:** Verify FK behavior

**Dependencies:** None

**Risk:** None — already correct

---

### Task 22: DB-037 — PO FK NOT NULL + RESTRICT

**Files to modify:**
- `app/database/schema.sql:122-123` — `supplier_id` and `product_id` already NOT NULL and RESTRICT

**Changes needed:**
1. Verify NOT NULL constraints exist (they do)
2. No change needed

**Migration required:** No (already correct)

**Test updates:** Verify NOT NULL enforcement

**Dependencies:** None

**Risk:** None — already correct

---

### Task 23: DB-038 — Statement/Lock Timeout

**Files to modify:**
- `app/database/connection.py:44-48` — `_DB_OPTIONS` already sets `statement_timeout=60000`, `lock_timeout=5000`
- Environment variables: `DB_STATEMENT_TIMEOUT_MS`, `DB_LOCK_TIMEOUT_MS`

**Changes needed:**
1. Verify timeouts are applied at connection level (they are)
2. Ensure ETL connections use different timeouts (they do via `_open_conn()`)
3. Document timeout values in README

**Migration required:** No

**Test updates:** Add test for statement timeout behavior

**Dependencies:** None

**Risk:** Low — already implemented

---

### Task 24: DB-039 — Pool Churn/Recycle/SSL

**Files to modify:**
- `app/database/connection.py:35-37` — Pool config: `_POOL_SIZE=20`, `_POOL_RECYCLE=1800`, `_POOL_TIMEOUT=30`
- `app/database/connection.py:132-133` — `minconn=_POOL_SIZE` to prevent churn
- `app/database/connection.py:159-162` — SSL mode support
- `app/database/connection.py:223-254` — `_validate_and_recycle_connection()` with birth timestamps

**Changes needed:**
1. Verify pool configuration prevents churn (minconn=maxconn)
2. Verify connection recycle by age works (birth timestamps)
3. Verify SSL mode honored
4. Consider reducing pool size for memory-constrained environments

**Migration required:** No

**Test updates:** Add pool stress test

**Dependencies:** None

**Risk:** Low — already implemented

---

### Task 25: DB-040 — Demo Users Env Guard

**Files to modify:**
- `app/database/seed.py` (check if exists) or `app/database/connection.py:465-467` `seed_database()`

**Changes needed:**
1. Guard demo user creation behind env var (e.g., `SEED_DEMO_USERS=true`)
2. Don't create demo users in production
3. Use strong random passwords for demo users

**Migration required:** No

**Test updates:** Test seed with/without env var

**Dependencies:** None

**Risk:** Low — simple env guard

---

### Task 26: DB-041 — ETL Session Refresh Upsert ✅ ALREADY DONE

**Status:** Already implemented in `etl_procedures.sql:260-304` (`etl_load_session_events`). Uses `ON CONFLICT (session_token) DO UPDATE` for session refresh.

**Files to verify:**
- `app/database/etl_procedures.sql:260-304`

**Validation:** Run ETL tests

---

### Task 27: DB-044 — AI Endpoints Write Role Guard

**Files to modify:**
- `app/routes/ai.py` — Check all AI endpoints have `@write_roles_required`
- `app/routes/api.py` — Check AI-related endpoints

**Changes needed:**
1. Audit all AI endpoints for proper RBAC
2. Add `@write_roles_required` where missing
3. Ensure forecast/anomaly/EOQ write endpoints require manager/admin

**Migration required:** No

**Test updates:** Add RBAC tests for AI endpoints

**Dependencies:** None

**Risk:** Low — decorator addition

---

### Task 28: DB-045 — Idempotency Keys (Constraint)

**Files to modify:**
- `app/database/schema.sql` — Add `idempotency_keys` table
- `app/database/procedures.sql` — Add `sp_idempotency_check()`, `sp_idempotency_record()`
- `app/utils/cache.py` or new `idempotency.py` — Python wrapper

**Changes needed:**
1. Create `idempotency_keys` table with `(key, user_id, created_at, response_json)`
2. Add unique constraint on `(key, user_id)`
3. Add stored procedures for check/record
4. Add middleware/decorator for API endpoints
5. Apply to POST/PUT/DELETE endpoints

**Migration required:** Yes — new table and procedures

**Test updates:** Add idempotency tests

**Dependencies:** None

**Risk:** Medium — new infrastructure

---

### Task 29: DB-047 — CHECK Constraints Migration ✅ ALREADY DONE

**Status:** Already implemented in `schema.sql:518-591`. CHECK constraints for non-negative values on products, suppliers, movements.

**Files to verify:**
- `app/database/schema.sql:518-591`

**Validation:** Run schema tests

---

### Task 30: DB-048 — UTC Pin at Connect ✅ ALREADY DONE

**Status:** Already implemented in `connection.py:44-48` — `_DB_OPTIONS` includes `-c TimeZone=UTC`.

**Files to verify:**
- `app/database/connection.py:44-48`

**Validation:** Verify timezone in tests

---

## Batch 3: Retention/Dead Objects (9 Issues)

### Task 31: DB-049 — Retention Procedures

**Files to modify:**
- `app/database/procedures.sql` — Add retention procedures
- `app/database/schema.sql` — Add retention config table if needed

**Changes needed:**
1. Create `sp_retention_cleanup_audit_log(days INT)` — delete audit_log older than N days
2. Create `sp_retention_cleanup_sessions(days INT)` — delete inactive sessions
3. Create `sp_retention_cleanup_rate_limits(days INT)` — cleanup rate_limit_state
4. Add cron job or scheduled task to run retention

**Migration required:** Yes — new procedures

**Test updates:** Add retention procedure tests

**Dependencies:** None

**Risk:** Low — standard cleanup procedures

---

### Task 32: DB-050 — PO CHECK Constraints ✅ ALREADY DONE

**Status:** Already in `schema.sql:130-133` — `chk_po_quantity_positive`, `chk_po_unit_cost_nonnegative`, `purchase_orders_status_chk`.

**Files to verify:**
- `app/database/schema.sql:130-133`

**Validation:** Run schema tests

---

### Task 33: DB-051 — Remove `sp_po_update_status`

**Files to modify:**
- `app/database/procedures.sql` — Remove `sp_po_update_status` if exists
- `app/repositories/po_repo.py:46-50` — `update_status()` calls it, should be removed
- `app/services/` — Any service using it

**Changes needed:**
1. Drop `sp_po_update_status` procedure
2. Remove `PurchaseOrderRepository.update_status()` method
3. Ensure all status changes go through `sp_po_transition` / `PurchaseOrderRepository.transition()`

**Migration required:** Yes — DROP FUNCTION migration

**Test updates:** Update tests to use `transition()` only

**Dependencies:** DB-003 (PO transition)

**Risk:** Low — removing dead code

---

### Task 34: DB-053 — `sp_user_delete` Soft Delete ✅ ALREADY DONE

**Status:** Already in `procedures.sql:723-729` and `procedures.sql:732-769` (updated list/find functions).

**Files to verify:**
- `app/database/procedures.sql:723-769`

**Validation:** Run user delete tests

---

### Task 35: DB-058 — Drop `fact_product_daily`

**Files to modify:**
- `app/database/schema.sql` — Drop table if exists
- `app/database/etl.py` — Remove references
- `app/database/etl_procedures.sql` — Remove references

**Changes needed:**
1. Check if `fact_product_daily` exists in schema
2. Drop table via migration
3. Remove any ETL code referencing it

**Migration required:** Yes — DROP TABLE migration

**Test updates:** Remove tests for dropped table

**Dependencies:** None

**Risk:** Low — dropping unused table

---

### Task 36: DB-059 — Remove `sp_record_movement_complete`

**Files to modify:**
- `app/database/procedures.sql` — Drop if exists
- `migrations/versions/20260924191107_add_sp_record_movement_complete_procedure.py` — This migration added it

**Changes needed:**
1. Drop `sp_record_movement_complete` procedure
2. Create migration to drop it
3. Verify no code calls it

**Migration required:** Yes — DROP FUNCTION migration

**Test updates:** None needed

**Dependencies:** None

**Risk:** Low — removing dead procedure

---

### Task 37: DB-060 — Drop `email_alert_log`

**Files to modify:**
- `app/database/schema.sql` — Drop table if exists
- Any code referencing it

**Changes needed:**
1. Check if `email_alert_log` table exists
2. Drop via migration
3. Remove references

**Migration required:** Yes — DROP TABLE migration

**Test updates:** None needed

**Dependencies:** None

**Risk:** Low — dropping unused table

---

### Task 38: DB-062 — Drop `mv_dashboard_metrics`

**Files to modify:**
- `app/database/schema.sql` — Drop materialized view if exists
- Any code refreshing it

**Changes needed:**
1. Check if `mv_dashboard_metrics` exists
2. Drop via migration
3. Remove refresh logic

**Migration required:** Yes — DROP MATERIALIZED VIEW migration

**Test updates:** None needed

**Dependencies:** None

**Risk:** Low — dropping unused view

---

### Task 39: DB-063 — Delete Dead Config Keys

**Files to modify:**
- `app/database/schema.sql` — Check `system_config_overrides` for dead keys
- `app/services/system_config_service.py` — Clean up

**Changes needed:**
1. Audit `system_config_overrides` for unused keys
2. Delete dead keys via migration or script
3. Document remaining keys

**Migration required:** Yes — DELETE statements in migration

**Test updates:** Verify config service works

**Dependencies:** None

**Risk:** Low — data cleanup

---

## Batch 4: Code Quality/Tests (11 Issues)

### Task 40: DB-064 — TestingConfig DB Name

**Files to modify:**
- `app/config/settings.py:127-132` — `TestingConfig` already uses `TEST_DB_NAME` env var with default `inventory_db_test`

**Changes needed:**
1. Verify `TestingConfig.DB_NAME` uses separate test database
2. Ensure CI sets `TEST_DB_NAME`
3. Document test database setup

**Migration required:** No

**Test updates:** Verify tests use test DB

**Dependencies:** None

**Risk:** Low — already implemented

---

### Task 41: DB-065 — `migrate.py` Timeout

**Files to modify:**
- `migrate.py:60-70` — `apply_upgrade()` uses subprocess with no timeout
- `migrate.py:73-83` — `apply_downgrade()` same

**Changes needed:**
1. Add timeout to `subprocess.run()` calls (e.g., 300 seconds)
2. Handle timeout exception gracefully
3. Log timeout appropriately

**Migration required:** No

**Test updates:** Test migration timeout handling

**Dependencies:** None

**Risk:** Low — simple subprocess timeout

---

### Task 42: DB-066 — Complete Downgrades

**Files to modify:**
- All migration files in `migrations/versions/` — Ensure `downgrade()` is implemented

**Changes needed:**
1. Audit all migrations for complete `downgrade()` implementation
2. Add missing downgrade logic
3. Test downgrade path

**Migration required:** Yes — modify existing migrations

**Test updates:** Test full upgrade/downgrade cycle

**Dependencies:** DB-022 (Alembic collision guards)

**Risk:** High — modifying migration history is risky

---

### Task 43: DB-067 — Double `AT TIME ZONE`

**Files to modify:**
- Search codebase for `AT TIME ZONE` usage
- `app/database/connection.py:47` — `_DB_OPTIONS` sets `TimeZone=UTC`
- `app/database/etl_procedures.sql` — Check for double conversion

**Changes needed:**
1. Find all `AT TIME ZONE` usages
2. Remove redundant conversions (connection already UTC)
3. Ensure timestamps stored as TIMESTAMPTZ

**Migration required:** No (code change only)

**Test updates:** Verify timestamp handling

**Dependencies:** DB-048 (UTC pin at connect)

**Risk:** Medium — timezone bugs are subtle

---

### Task 44: DB-068 — Seed ON CONFLICT

**Files to modify:**
- `app/database/seed.py` (check if exists) or `seed_database()`

**Changes needed:**
1. Update seed script to use `ON CONFLICT DO NOTHING` or `DO UPDATE`
2. Make seed idempotent
3. Handle unique constraint violations gracefully

**Migration required:** No

**Test updates:** Test seed on fresh and existing DB

**Dependencies:** DB-001 (SKU unique), DB-009 (PO unique)

**Risk:** Low — seed script improvement

---

### Task 45: DB-069 — Notification Dedup Key

**Files to modify:**
- `app/database/schema.sql:407-416` — `notifications` table
- `app/repositories/notification_repo.py`
- `app/services/notification_service.py`

**Changes needed:**
1. Add `dedup_key` column to `notifications` table
2. Add unique constraint on `(user_id, dedup_key)` where dedup_key not null
3. Update notification creation to use dedup_key
4. Modify `NotificationRepository` to handle upsert

**Migration required:** Yes — ALTER TABLE ADD COLUMN + UNIQUE CONSTRAINT

**Test updates:** Add notification dedup tests

**Dependencies:** None

**Risk:** Medium — schema change + logic

---

### Task 46: DB-070 — Cache Key Prefixes

**Files to modify:**
- `app/utils/cache.py:154-165` — `make_key()` function
- All cache usage sites

**Changes needed:**
1. Standardize cache key prefixes (e.g., `products:`, `suppliers:`, `reports:`)
2. Ensure `make_key(prefix="products", ...)` used consistently
3. Update `cache_bust_*()` functions to match prefixes

**Migration required:** No

**Test updates:** Verify cache invalidation works

**Dependencies:** None

**Risk:** Low — cache key standardization

---

### Task 47: DB-071 — Bust `reorder_count` on Movement/PO

**Files to modify:**
- `app/utils/cache.py:124-131` — `cache_bust_movements()` and `cache_bust_purchase_orders()`
- `app/__init__.py:232-239` — `_fetch_reorder_count()` uses `global_cache.get_or_set("reorder_count", ...)`

**Changes needed:**
1. Verify `cache_bust_movements()` invalidates `global_cache` (line 126: `n += global_cache.invalidate("")` — yes)
2. Verify `cache_bust_purchase_orders()` invalidates `global_cache` (line 136: `n += products_cache.invalidate("")` but not global_cache directly)
3. Add `global_cache.invalidate("")` to `cache_bust_purchase_orders()`

**Migration required:** No

**Test updates:** Add test for reorder_count cache busting

**Dependencies:** None

**Risk:** Low — cache invalidation fix

---

### Task 48: DB-072 — `cache_bust_suppliers` Prefix

**Files to modify:**
- `app/utils/cache.py:116-121` — `cache_bust_suppliers()`

**Changes needed:**
1. Verify `cache_bust_suppliers()` uses correct prefixes
2. Currently invalidates `suppliers_cache`, `reports_cache` (with `reports:` prefix), `api_cache` (with `suppliers` prefix), `landing_cache`
3. Ensure consistency with `make_key()` prefixes

**Migration required:** No

**Test updates:** Verify supplier cache busting

**Dependencies:** DB-070 (cache key prefixes)

**Risk:** Low — cache invalidation fix

---

### Task 49: DB-073 — Forecast Upsert ✅ ALREADY DONE

**Status:** Already implemented via unique index `uq_forecast_cache_key` in `schema.sql:234-235` and `ForecastRepository.save()` uses upsert.

**Files to verify:**
- `app/database/schema.sql:227-235`
- `app/repositories/forecast_repo.py` (check for upsert logic)
- `tests/test_db_integrity_fixes.py:322-344` — `test_d7_forecast_save_is_idempotent`

**Validation:** Run existing test

---

### Task 50: DB-074 — 404 on Missing ID

**Files to modify:**
- `app/routes/api.py:163-172` — `get_product()` returns 404 if not found
- `app/routes/api.py:227-236` — `get_supplier()` returns 404 if not found
- Check all GET-by-ID endpoints

**Changes needed:**
1. Audit all GET-by-ID endpoints for 404 on missing resource
2. Ensure consistent error format: `api_error("NOT_FOUND", "Resource not found.", status=404)`
3. Add missing 404 handling

**Migration required:** No

**Test updates:** Add 404 tests for all GET-by-ID endpoints

**Dependencies:** None

**Risk:** Low — endpoint consistency

---

## Batch 5: Remaining Low (20 Issues)

### Task 51: DB-075 — Audit Attribution (Partial)

**Files to modify:**
- `app/database/triggers.sql` — Audit triggers
- `app/security/dberrors.py` — Error translation

**Changes needed:**
1. Ensure audit logs capture user_id for all operations
2. Fix any missing attribution in triggers
3. Add user_id to audit_log where missing

**Migration required:** No (trigger updates)

**Test updates:** Verify audit attribution

**Dependencies:** None

**Risk:** Low — trigger updates

---

### Task 52: DB-076 — GET `request.args`

**Files to modify:**
- `app/routes/api.py:147-154` — `list_products()` uses `request.form.get("warehouse", "")` instead of `request.args.get()`
- Check all GET endpoints for `request.form` vs `request.args`

**Changes needed:**
1. Fix `list_products()` to use `request.args.get("warehouse", "")`
2. Audit all GET endpoints for correct request data access
3. Use `request.args` for GET, `request.get_json()` for POST/PUT

**Migration required:** No

**Test updates:** Test GET with query params

**Dependencies:** None

**Risk:** Low — simple fix

---

### Task 53: DB-077 — Registration Unique Violation ✅ ALREADY DONE

**Status:** Already in `auth_service.py:50-62` — catches `UniqueViolation` and raises `AuthError`.

**Files to verify:**
- `app/services/auth_service.py:50-62`
- `tests/test_auth.py` — Should have registration tests

**Validation:** Run auth tests

---

### Task 54: DB-078 — Password Reset Atomic

**Files to modify:**
- `app/services/auth_service.py:271-298` — `reset_password()`
- `app/repositories/user_repo.py:100-114` — Token find/consume/purge

**Changes needed:**
1. Wrap token validation + password update + token consume in single transaction
2. Use `get_cursor(commit=True)` for the entire operation
3. Prevent race where token used twice

**Migration required:** No

**Test updates:** Add concurrent password reset test

**Dependencies:** None

**Risk:** Medium — transaction boundary change

---

### Task 55: DB-079 — After-Commit Best-Effort (Doc)

**Files to modify:**
- `app/utils/cache.py` — Add documentation
- `app/services/` — Document best-effort notifications

**Changes needed:**
1. Document that cache busting, notifications, audit are best-effort after commit
2. Add comments in code where after-commit actions happen
3. Consider using `after_commit` hooks if needed

**Migration required:** No

**Test updates:** None (documentation)

**Dependencies:** None

**Risk:** None — documentation only

---

### Task 56: DB-080 — Partial SKU Index ✅ ALREADY DONE

**Status:** Already in `schema.sql:88-117` — Partial unique index `products_sku_live_key WHERE deleted_at IS NULL`.

**Files to verify:**
- `app/database/schema.sql:88-117`

**Validation:** Run SKU uniqueness tests

---

### Task 57: DB-081 — Monitoring Alert Dedup

**Files to modify:**
- `app/database/schema.sql:383-401` — `model_monitoring_alerts` table
- `app/services/forecast_service.py` or monitoring service

**Changes needed:**
1. Add unique constraint or dedup logic for monitoring alerts
2. Prevent duplicate alerts for same SKU/model/type/date
3. Consider unique index on `(sku, model_name, alert_type, alert_date)`

**Migration required:** Yes — ADD CONSTRAINT or UNIQUE INDEX

**Test updates:** Add monitoring alert dedup test

**Dependencies:** None

**Risk:** Low — unique constraint addition

---

### Task 58: DB-082 — UTC Default Alignment (Doc)

**Files to modify:**
- `app/database/schema.sql` — Document TIMESTAMPTZ defaults
- `app/config/settings.py` — Document UTC usage

**Changes needed:**
1. Document that all timestamps are UTC
2. Ensure `NOW()` vs `NOW() AT TIME ZONE 'UTC'` consistency
3. Add comment in schema.sql

**Migration required:** No

**Test updates:** None (documentation)

**Dependencies:** DB-048, DB-067

**Risk:** None — documentation only

---

### Task 59: DB-083 — Timestamptz Branch TypeError

**Files to modify:**
- Search for `timestamptz` handling in Python code
- `app/database/connection.py` — Cursor factory uses `RealDictCursor`
- Check for timezone-naive vs aware comparisons

**Changes needed:**
1. Find TypeError related to timestamptz
2. Ensure all datetime comparisons use timezone-aware UTC
3. Use `_utcnow()` helper from `auth_service.py`

**Migration required:** No

**Test updates:** Add timezone handling tests

**Dependencies:** DB-048, DB-067

**Risk:** Medium — timezone bugs

---

### Task 60: DB-084 — Uniform FK Policy

**Files to modify:**
- `app/database/schema.sql` — Audit all FKs

**Changes needed:**
1. Document FK policy: RESTRICT for all FKs except:
   - CASCADE: `user_settings.user_id`, `password_reset_tokens.user_id`, `user_sessions.user_id`
   - SET NULL: `products.supplier_id` (supplier soft delete)
2. Verify all FKs follow policy
3. Create migration for any violations

**Migration required:** Yes — if any FKs violate policy

**Test updates:** Verify FK behavior

**Dependencies:** DB-035, DB-036, DB-037

**Risk:** Medium — FK changes can break things

---

### Task 61: DB-085 — Pool Stats `in_use`

**Files to modify:**
- `app/database/connection.py:417-431` — `get_pool_stats()` already returns `in_use: len(_CHECKOUT_TIMES)`

**Changes needed:**
1. Verify `in_use` count is accurate
2. Add more pool stats if needed (idle, waiting)
3. Expose via monitoring endpoint

**Migration required:** No

**Test updates:** Test pool stats accuracy

**Dependencies:** DB-039

**Risk:** Low — already implemented

---

### Task 62: DB-086 — Bootstrap Fail Fast ✅ ALREADY DONE

**Status:** Already in `app/__init__.py:122-132` — Fails fast in production, logs warning in development.

**Files to verify:**
- `app/__init__.py:122-132`

**Validation:** Test bootstrap failure handling

---

### Task 63: DB-087 — ETL Honest Status + Try/Finally

**Files to modify:**
- `app/database/etl.py:469-738` — `run_etl()` function

**Changes needed:**
1. Ensure `run_etl()` returns honest status (already has `warehouse_etl_ok` flag)
2. Verify all `try/finally` blocks release advisory lock
3. Ensure connection always closed in `finally`
4. Add more granular status reporting

**Migration required:** No

**Test updates:** Test ETL failure scenarios

**Dependencies:** None

**Risk:** Low — error handling improvement

---

### Task 64: DB-088 — `migrate.py etl` Command

**Files to modify:**
- `migrate.py:106-127` — Add `etl` command

**Changes needed:**
1. Add `etl` command to `migrate.py` CLI
2. Call `etl_database()` from app context
3. Support `--force` flag

**Migration required:** No

**Test updates:** Test CLI command

**Dependencies:** None

**Risk:** Low — CLI addition

---

### Task 65: DB-061 — Dead Scripts Cleanup

**Files to modify:**
- Root directory: `debug_time.py`, `check_columns.py`, `debug_schema.py`, `bump_versions.py`, `check_procs.py`, `check_func2.py`, `fix_db.py`, `load_proc.py`, `apply_procedures.py`, `test.py`

**Changes needed:**
1. Audit root scripts for dead/unused code
2. Remove or archive unused scripts
3. Keep only: `run.py`, `migrate.py`, `apply_procedures.py` (if used)

**Migration required:** No

**Test updates:** None

**Dependencies:** None

**Risk:** Low — cleanup

---

### Task 66: DB-034 — Warehouse/ETL Re-apply Migration (Duplicate)

**Status:** Duplicate of Task 19. Skip.

---

### Task 67: DB-010 — Anomaly Log Dedup ✅ ALREADY DONE

**Status:** Already in `schema.sql:213-225` — Unique index `uq_anomaly_detection` on `(product_id, COALESCE(alert_date, detected_at::date), anomaly_type, COALESCE(detection_method, 'zscore'))`.

**Files to verify:**
- `app/database/schema.sql:213-225`
- `tests/test_db_integrity_fixes.py:293-319` — `test_d6_anomaly_save_is_idempotent`

**Validation:** Run existing test

---

### Task 68: DB-011 — Forecast Cache Dedup ✅ ALREADY DONE

**Status:** Already in `schema.sql:227-235` — Unique index `uq_forecast_cache_key` on `(product_id, model, horizon)`.

**Files to verify:**
- `app/database/schema.sql:227-235`
- `tests/test_db_integrity_fixes.py:322-344` — `test_d7_forecast_save_is_idempotent`

**Validation:** Run existing test

---

## Implementation Order Summary

### Phase 1: Schema & Constraints (Tasks 20-22, 29, 30, 32, 35-39, 56, 60, 67, 68)
- Verify existing constraints (mostly done)
- Add missing constraints (idempotency keys, notification dedup, monitoring alert dedup)
- Drop dead objects
- **Migration required:** Yes for new constraints and drops

### Phase 2: Stored Procedures (Tasks 1, 2, 5, 7, 26, 33, 34, 36)
- Verify atomic procedures (mostly done)
- Remove dead procedures
- **Migration required:** Yes for DROP FUNCTION

### Phase 3: Python Services & Repositories (Tasks 3, 4, 6, 8, 9, 10, 27, 44, 45, 47, 48, 50, 51, 52, 54)
- Error translation fixes
- Service logic updates
- Cache invalidation fixes
- **Migration required:** No

### Phase 4: API Routes & RBAC (Tasks 27, 44, 50, 52)
- Add missing endpoints
- Fix RBAC on AI endpoints
- Fix GET request.args usage
- **Migration required:** No

### Phase 5: Configuration & Infrastructure (Tasks 11, 12, 13, 14, 15, 16, 17, 18, 23, 24, 25, 40, 41, 42, 43, 55, 58, 59, 61, 62, 63, 64, 65)
- Migration tooling fixes
- Pool configuration
- Health checks
- Demo user guards
- Documentation
- Dead script cleanup
- **Migration required:** No (except migration tooling)

### Phase 6: ETL & Warehouse (Tasks 19, 28, 31, 49, 67, 68)
- ETL watermark (done)
- Idempotency keys
- Retention procedures
- Forecast/anomaly dedup (done)
- **Migration required:** Yes for idempotency keys table

### Phase 7: Testing (All tasks)
- Add/update tests for each fix
- Run full test suite
- Verify no regressions

---

## Testing Strategy

### Unit Tests
- `tests/test_db_integrity_fixes.py` — Core integrity tests (already exist)
- `tests/test_auth.py` — Auth flow tests
- `tests/test_services.py` — Service layer tests
- `tests/test_repositories.py` — Repository tests (add if missing)
- `tests/test_cache.py` — Cache invalidation tests

### Integration Tests
- `tests/test_api.py` — API endpoint tests
- `tests/test_etl.py` — ETL pipeline tests
- `tests/test_migrations.py` — Migration upgrade/downgrade tests

### E2E Tests
- Critical user flows: login, product CRUD, stock movements, PO lifecycle
- Concurrent movement test (already in `test_db_integrity_fixes.py`)
- Race condition tests for SKU/PO creation

### Security Tests
- `tests/test_security.py` — SQL injection, XSS, CSRF, RBAC
- `tests/test_auth_lockout.py` — Rate limiting
- `tests/test_admin_*.py` — Admin endpoint security

### Performance Tests
- Dashboard load time
- ETL runtime
- Connection pool behavior under load

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|------|-------------|------------|
| **Migration conflicts** | Multiple migrations modifying same tables | Apply in dependency order; test on staging first |
| **FK constraint violations** | Changing FK actions breaks existing data | Verify data integrity before applying; use `NOT VALID` + `VALIDATE` |
| **Cache invalidation gaps** | Stale data served after writes | Add cache busting tests; verify all write paths call bust functions |
| **Timezone bugs** | Double `AT TIME ZONE` or naive/aware mix | Audit all datetime handling; use `_utcnow()` consistently |
| **ETL data loss** | Watermark bugs skip rows | Test incremental ETL with late-arriving data |
| **Pool exhaustion** | Connection leaks under load | Monitor `in_use` stats; add leak detection alerts |
| **Race conditions** | SKU/PO unique violations under concurrency | Verify error translation catches all `UniqueViolation` cases |

---

## Success Criteria

- [ ] All unit tests pass (`pytest` coverage ≥ 80%)
- [ ] All integration tests pass
- [ ] All E2E tests pass for critical flows
- [ ] Security review passes (no critical/high issues)
- [ ] Performance benchmarks meet targets (dashboard < 500ms, ETL < 60s)
- [ ] Documentation updated (README, API docs, migration guide)
- [ ] Manual verification completed on staging

---

## Dependencies

### Internal
- DB-001 → DB-033 (SKU unique handling for CSV import)
- DB-003 → DB-008, DB-025 (PO transition for mark-ordered and receive)
- DB-009 → DB-010 (PO unique error translation for auto-draft)
- DB-022 → DB-042 (Alembic guards for complete downgrades)
- DB-039 → DB-014, DB-061 (Pool config for health check and stats)
- DB-048 → DB-043, DB-059 (UTC pin for timezone fixes)
- DB-070 → DB-047, DB-048 (Cache prefixes for busting)

### External
- PostgreSQL 15+ (for `IF NOT EXISTS` on constraints, advisory locks)
- psycopg2 2.9+ (for error code handling)
- Flask-Limiter (for rate limiting)
- Render/Deployment platform (for blueprint config)

### Data Migrations
- SKU deduplication for partial unique index (already in `schema.sql:97-117`)
- Anomaly log deduplication (already in `schema.sql:216-222`)
- Forecast cache deduplication (already in `schema.sql:228-233`)
- Dead table/view cleanup (Tasks 35, 37, 38)

---

## Rollback Plan

### Database
- Each migration has `downgrade()` function (Task 42)
- For constraint additions: `ALTER TABLE ... DROP CONSTRAINT IF EXISTS ...`
- For table drops: Recreate from schema.sql backup
- For procedure drops: Recreate from procedures.sql backup

### Code
- Git revert commits for each task
- Feature flags for new functionality (idempotency keys, retention procedures)
- Cache invalidation changes are backward compatible

### Configuration
- Environment variable guards (demo users, timeouts) can be toggled
- Pool settings via env vars (`DB_POOL_SIZE`, `DB_POOL_RECYCLE`, etc.)

---

## Plan Complete

This plan covers all 68 issues across 5 batches. Many issues are already implemented (marked ✅). The remaining work focuses on:
1. Verifying existing fixes
- Adding missing error translations
- Cleaning up dead code/objects
- Adding new constraints (idempotency, notification dedup)
- Improving tooling (migrate.py, health checks)
- Documentation

**Recommended execution approach:** Subagent-driven for Phases 1-3 (database/schema changes need careful review), Native for Phases 4-7 (Python code changes are more straightforward).