# Implementation Plan: ADM-001 — Data Import Movements Bypass Atomic Stock Validation

## Overview

The CSV data import for movements (`_import_movements` in `app/routes/admin/data_import_routes.py:289-315`) performs a direct `INSERT INTO movements` instead of calling the atomic stored procedure `sp_movement_record`. This bypasses the row-level lock, stock validation, and atomic stock delta update that `sp_movement_record` provides, creating a race condition where concurrent imports can drive stock negative.

**Fix Direction**: Replace the direct INSERT with a call to `sp_movement_record` per row (Option A from research).

---

## 1. Exact Problem to Solve

**Current behavior**: When importing movements via CSV, the code executes:
```sql
INSERT INTO movements (product_id, quantity, type, reason)
VALUES (%s, %s, %s, %s)
```

**Problem**: This direct INSERT:
- Does NOT acquire a row lock on `products` (`FOR UPDATE`)
- Does NOT validate stock atomically with the insert
- Relies on `trg_validate_movement` trigger which reads `current_stock` WITHOUT a lock
- Creates a race window: concurrent imports read stale stock, all pass validation, all insert, stock goes negative

**Required behavior**: Each imported movement row must go through `sp_movement_record` which:
1. Locks the product row (`SELECT ... FOR UPDATE`)
2. Validates stock won't go negative under the lock
3. Inserts movement row AND updates `products.current_stock` in ONE transaction
4. Returns the new movement ID

---

## 2. Root Cause

**File**: `app/routes/admin/data_import_routes.py`, function `_import_movements` (lines 289-315)

**Code path**:
```
_import_movements (direct INSERT)
    → movements table
    → trg_validate_movement (BEFORE INSERT trigger, NO lock)
    → trg_log_movement_create (AFTER INSERT trigger, audit only)
    → products.current_stock NEVER updated
```

**Correct path** (used by UI/API):
```
MovementService.record
    → MovementRepository.record
    → sp_movement_record (row lock + validation + atomic delta + insert)
    → trg_log_movement_create (audit)
    → products.current_stock UPDATED atomically
```

---

## 3. Files/Components Affected

| File | Component | Change Type |
|------|-----------|-------------|
| `app/routes/admin/data_import_routes.py` | `_import_movements` function | **MODIFY** — Replace direct INSERT with `sp_movement_record` call |
| `app/routes/admin/data_import_routes.py` | `_execute_with_lock` helper | **REVIEW** — Advisory lock still needed for batch serialization |
| `tests/test_db_integrity_fixes.py` | Test suite | **EXTEND** — Add import-specific concurrency test |

---

## 4. Database Objects Affected

| Object | Role | Impact |
|--------|------|--------|
| `sp_movement_record` | Atomic movement recording (row lock + validation + stock delta) | **Now called by import path** |
| `trg_validate_movement` | BEFORE INSERT trigger on `movements` | Still fires but now redundant (validation already done in SP) — harmless |
| `trg_log_movement_create` | AFTER INSERT trigger on `movements` | Still fires for audit — works correctly |
| `movements` table | Movement ledger | Inserted via SP instead of direct INSERT |
| `products.current_stock` | Current stock column | Now updated atomically via SP |
| `audit_log` | Audit trail | Populated via trigger (unchanged) |

**No schema migration needed** — all objects already exist.

---

## 5. Implementation Steps

### Phase 1: Core Fix — Replace Direct INSERT with SP Call

#### Step 1.1: Modify `_import_movements` to call `sp_movement_record` (File: `app/routes/admin/data_import_routes.py`)
- **Action**: Replace the `cur.execute("INSERT INTO movements ...")` block with a call to `SELECT sp_movement_record(...)`
- **Why**: This is the single smallest change that fixes the race condition
- **Dependencies**: None
- **Risk**: Low — SP already exists and is battle-tested
- **Validation**: 
  - Unit test: Verify SP is called with correct parameters
  - Integration test: Import a CSV with movements, verify stock updated correctly
  - Concurrency test: Run concurrent imports, verify stock never negative

#### Step 1.2: Handle `reference` and `notes` fields from CSV (File: `app/routes/admin/data_import_routes.py`)
- **Action**: Map CSV `reason` column to SP's `reference` parameter; add optional `notes` support
- **Why**: `sp_movement_record` accepts `reference` and `notes` — currently unused in import
- **Dependencies**: Step 1.1
- **Risk**: Low
- **Validation**: Import CSV with `reason` column, verify `reference` populated in `movements` table

#### Step 1.3: Preserve advisory lock for batch serialization (File: `app/routes/admin/data_import_routes.py`)
- **Action**: Keep `_execute_with_lock` wrapper around the import loop
- **Why**: Serializes concurrent import batches for the same entity (prevents interleaved batches)
- **Dependencies**: Step 1.1
- **Risk**: Low — existing pattern
- **Validation**: Verify advisory lock acquired/released around import

#### Step 1.4: Error handling — continue on individual row failure, collect errors (File: `app/routes/admin/data_import_routes.py`)
- **Action**: Wrap each `sp_movement_record` call in try/except; collect failed rows with error messages; continue processing remaining rows
- **Why**: Current code silently continues on exception; need visibility into which rows failed
- **Dependencies**: Step 1.1
- **Risk**: Medium — error collection logic must not break transaction semantics
- **Validation**: Import CSV with mix of valid/invalid rows; verify valid rows imported, errors reported

### Phase 2: Testing

#### Step 2.1: Add unit test for `_import_movements` SP call (File: `tests/test_data_import_movements.py` — new file)
- **Action**: Mock `get_cursor`, verify `sp_movement_record` called with correct params per row
- **Why**: Fast feedback on parameter mapping
- **Dependencies**: Step 1.1
- **Risk**: Low

#### Step 2.2: Add integration test — basic import updates stock (File: `tests/test_data_import_movements.py`)
- **Action**: Create product with stock=10, import OUT movement qty=3, verify stock=7 and movement row exists
- **Why**: End-to-end verification of stock delta
- **Dependencies**: Step 1.1
- **Risk**: Low

#### Step 2.3: Add concurrency test — concurrent imports cannot drive stock negative (File: `tests/test_data_import_movements.py`)
- **Action**: Mirror `test_d1_concurrent_out_movements_cannot_go_negative` but use `_import_movements` path
- **Why**: Validates the fix closes the race window
- **Dependencies**: Step 1.1, 1.4
- **Risk**: Medium — threading tests can be flaky; use deterministic setup

#### Step 2.4: Add regression test — invalid rows don't block valid rows (File: `tests/test_data_import_movements.py`)
- **Action**: Import CSV with 3 valid + 2 invalid rows; verify 3 succeed, 2 errors collected
- **Why**: Validates error handling requirement
- **Dependencies**: Step 1.4
- **Risk**: Low

#### Step 2.5: Run existing test suite to ensure no regressions
- **Action**: `pytest tests/test_db_integrity_fixes.py -v`
- **Why**: Existing tests validate the correct path still works
- **Dependencies**: All above
- **Risk**: Low

---

## 6. Test Requirements

| Test Type | Coverage | Location |
|-----------|----------|----------|
| **Unit** | `_import_movements` calls `sp_movement_record` with correct params | `tests/test_data_import_movements.py` |
| **Integration** | Import CSV → stock updated, movement row created, audit logged | `tests/test_data_import_movements.py` |
| **Concurrency** | 5 threads × OUT 3 on stock 10 → exactly 3 succeed, stock=1 | `tests/test_data_import_movements.py` |
| **Regression** | Invalid rows skipped, valid rows imported, errors returned | `tests/test_data_import_movements.py` |
| **Existing** | `test_d1_concurrent_out_movements_cannot_go_negative` still passes | `tests/test_db_integrity_fixes.py` |

**Minimum coverage**: 80% on new test file; all existing tests must pass.

---

## 7. Regression Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| SP call signature mismatch | Low | High | Verify SP signature in `procedures.sql:227-270` matches call |
| Advisory lock deadlock | Low | Medium | Lock is per-entity (movements=0x6D6F7665); short hold time |
| Trigger double-validation | None | None | `trg_validate_movement` still fires but reads post-SP stock (already valid) — harmless |
| CSV column mapping break | Medium | Medium | Map `reason`→`reference`, add optional `notes`; document expected columns |
| Transaction boundary issues | Medium | High | Each SP call in its own transaction (via `get_cursor(commit=True)`); advisory lock spans batch |

---

## 8. Security Considerations

| Aspect | Status | Notes |
|--------|--------|-------|
| SQL Injection | ✅ Safe | SP called via parameterized query (`cur.execute("SELECT sp_movement_record(%s, %s, %s, %s, %s, %s)", ...)`) |
| Input Validation | ✅ Required | Validate `product_id`, `qty`, `movement_type` before SP call (already done in current code) |
| Authorization | ✅ Enforced | Route protected by `@write_roles_required` (admin/manager only) |
| Rate Limiting | ✅ Enforced | `@limiter.limit("10 per minute")` on upload endpoint |
| Audit Trail | ✅ Preserved | `trg_log_movement_create` still fires for each movement |

---

## 9. Rollback Considerations

| Component | Rollback Method |
|-----------|-----------------|
| **Code** | Revert `app/routes/admin/data_import_routes.py` to direct INSERT (git revert) |
| **Database** | No schema changes — no rollback needed |
| **Data** | If bad import occurred: manual stock correction via `sp_product_set_stock` or compensating movements |
| **Configuration** | No config changes |

**Rollback time**: < 5 minutes (code revert + redeploy)

---

## 10. Expected Final Behavior

After fix:
1. **CSV Import** → `_import_movements` → calls `sp_movement_record` per row
2. **Each row**: Product row locked → stock validated → movement inserted → stock updated atomically
3. **Concurrent imports**: Serialized by advisory lock + SP row lock → no negative stock possible
4. **Invalid rows**: Caught, logged, skipped → valid rows still imported
5. **Audit**: `trg_log_movement_create` fires for each successful movement
6. **Response**: Flash message shows count imported; errors (if any) surfaced to user

---

## Implementation Checklist

- [ ] Step 1.1: Replace INSERT with `sp_movement_record` call
- [ ] Step 1.2: Map `reason` → `reference`, support `notes`
- [ ] Step 1.3: Preserve advisory lock wrapper
- [ ] Step 1.4: Add error collection for failed rows
- [ ] Step 2.1: Unit test for SP call
- [ ] Step 2.2: Integration test for stock update
- [ ] Step 2.3: Concurrency test (mirror D-1 test)
- [ ] Step 2.4: Regression test for partial failure
- [ ] Step 2.5: Run full existing test suite
- [ ] Manual verification: Import CSV via UI, verify stock, movements, audit
- [ ] Update asset version in `base.html` if JS/CSS changed (not expected)

---

## Success Criteria

- [ ] All unit tests pass (pytest coverage ≥ 80% on new test file)
- [ ] All integration tests pass
- [ ] Concurrency test passes: 5 concurrent OUT imports on stock=10 → exactly 3 succeed, final stock=1
- [ ] Existing test `test_d1_concurrent_out_movements_cannot_go_negative` still passes
- [ ] Security review passes (no new vulnerabilities)
- [ ] Manual CSV import via UI works correctly
- [ ] Documentation updated (if CSV column expectations changed)