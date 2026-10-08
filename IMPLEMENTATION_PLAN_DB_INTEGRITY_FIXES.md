# Implementation Plan: DB Integrity Fixes (DB-001, DB-009, DB-021)

## Overview

This plan addresses three database integrity issues in the Inventory Logistics Optimization Dashboard:
1. **DB-001 (Task 3)**: Fix `create_product()` API to catch `ProductError` specifically and return HTTP 409 for unique SKU violations
2. **DB-009 (Task 4)**: Add REST API endpoint `/api/purchase-orders` POST for purchase order creation
3. **DB-021 (Task 6)**: Remove `current_stock` parameter from `sp_product_update` stored procedure signature entirely, update repository and service layers

All changes follow TDD methodology: write tests first, then implement.

---

## Requirements

- **DB-001**: API `create_product()` must catch `ProductError` (not generic `Exception`) and return 409 for unique violations, 422 for validation errors
- **DB-009**: Add `/api/purchase-orders` POST endpoint with proper validation, error handling, and audit logging
- **DB-021**: Remove `current_stock` from `sp_product_update` signature; update `ProductRepository.update()` and `ProductService.validate_payload()` to reject `current_stock` in updates
- **Testing**: Add tests for PO unique violation (409), 409 vs 422 differentiation, and product edit bypass prevention
- **No migrations needed**: Schema already correct (unique constraints exist)

---

## Architecture Changes

| Change | File | Description |
|--------|------|-------------|
| 1 | `app/routes/api.py` | Fix `create_product()` exception handling; add `create_purchase_order()` endpoint |
| 2 | `app/database/procedures.sql` | Remove `p_current_stock` parameter from `sp_product_update` |
| 3 | `app/repositories/product_repo.py` | Update `update()` to not pass `current_stock` |
| 4 | `app/services/product_service.py` | Update `validate_payload()` to reject `current_stock` in updates |
| 5 | `tests/test_db_integrity_fixes.py` | Add tests for PO unique violation, 409/422 differentiation, product edit bypass |

---

## Implementation Steps

### Phase 1: Database Layer (Stored Procedure)

#### Step 1.1: Remove `current_stock` from `sp_product_update` signature
**File**: `app/database/procedures.sql` (lines 80-99)
- **Action**: Remove `p_current_stock INT DEFAULT 0` parameter from `sp_product_update` function signature and all references
- **Why**: DB-021 requires stock changes ONLY via `sp_movement_record` (atomic delta + ledger). The parameter was kept for "signature compatibility" but must now be removed entirely.
- **Dependencies**: None (first step)
- **Risk**: Low — stored procedure is only called from `ProductRepository.update()`
- **Validation**: Run `sp_product_update` with new signature; verify it still updates other fields correctly

```sql
-- BEFORE (lines 80-86):
CREATE OR REPLACE FUNCTION sp_product_update(
    p_id INT, p_name VARCHAR, p_category VARCHAR DEFAULT '',
    p_warehouse VARCHAR DEFAULT 'WH-Pune', p_unit_price NUMERIC DEFAULT 0,
    p_supplier_id INT DEFAULT NULL, p_current_stock INT DEFAULT 0,
    p_reorder_point INT DEFAULT 0, p_demand_rate NUMERIC DEFAULT 0,
    p_ordering_cost NUMERIC DEFAULT 0, p_holding_cost NUMERIC DEFAULT 0
) RETURNS VOID AS $$

-- AFTER:
CREATE OR REPLACE FUNCTION sp_product_update(
    p_id INT, p_name VARCHAR, p_category VARCHAR DEFAULT '',
    p_warehouse VARCHAR DEFAULT 'WH-Pune', p_unit_price NUMERIC DEFAULT 0,
    p_supplier_id INT DEFAULT NULL, p_reorder_point INT DEFAULT 0,
    p_demand_rate NUMERIC DEFAULT 0, p_ordering_cost NUMERIC DEFAULT 0,
    p_holding_cost NUMERIC DEFAULT 0
) RETURNS VOID AS $$
```

---

### Phase 2: Repository Layer

#### Step 2.1: Update `ProductRepository.update()` to not pass `current_stock`
**File**: `app/repositories/product_repo.py` (lines 90-103)
- **Action**: Remove `current_stock` from the `sp_product_update` call parameters
- **Why**: Match the updated stored procedure signature
- **Dependencies**: Step 1.1 (stored procedure must be updated first)
- **Risk**: Low — single call site, straightforward parameter removal
- **Validation**: Run existing product update tests; verify no `current_stock` in call

```python
# BEFORE (lines 92-102):
cur.execute(
    "SELECT sp_product_update(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
    (
        product_id,
        payload["name"], payload.get("category"),
        payload.get("warehouse"), payload.get("unit_price"),
        payload.get("supplier_id"), int(payload.get("current_stock") or 0),
        int(payload.get("reorder_point") or 0),
        payload.get("demand_rate"), payload.get("ordering_cost"),
        payload.get("holding_cost"),
    ),
)

# AFTER:
cur.execute(
    "SELECT sp_product_update(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
    (
        product_id,
        payload["name"], payload.get("category"),
        payload.get("warehouse"), payload.get("unit_price"),
        payload.get("supplier_id"),
        int(payload.get("reorder_point") or 0),
        payload.get("demand_rate"), payload.get("ordering_cost"),
        payload.get("holding_cost"),
    ),
)
```

---

### Phase 3: Service Layer

#### Step 3.1: Update `ProductService.validate_payload()` to reject `current_stock` in updates
**File**: `app/services/product_service.py` (lines 61-65)
- **Action**: Remove the `current_stock` handling block (lines 61-65) entirely. The comment says "Only include current_stock if explicitly provided (DB-021: prevent partial-PUT zeroing)" — now we must reject it entirely.
- **Why**: DB-021 — stock changes ONLY via movements. Product edit must not accept `current_stock`.
- **Dependencies**: Step 2.1 (repository updated)
- **Risk**: Low — validation logic only
- **Validation**: Test that sending `current_stock` in PUT `/api/products/<id>` returns 422

```python
# REMOVE lines 61-65 entirely:
# # Only include current_stock if explicitly provided (DB-021: prevent partial-PUT zeroing)
# if "current_stock" in payload:
#     payload["current_stock"] = int(payload.get("current_stock") or 0)
#     if payload["current_stock"] < 0:
#         raise ValidationError("Current stock cannot be negative.")
```

---

### Phase 4: API Layer — DB-001 Fix

#### Step 4.1: Fix `create_product()` exception handling
**File**: `app/routes/api.py` (lines 175-189)
- **Action**: Catch `ProductError` specifically; check error message for "SKU already exists" to return 409; other `ProductError` → 422
- **Why**: Currently catches generic `Exception` and returns 422 for everything. Unique violations should be 409.
- **Dependencies**: None (can be done in parallel with Phase 1-3)
- **Risk**: Medium — must import `ProductError` and handle correctly
- **Validation**: Test duplicate SKU returns 409; invalid payload returns 422

```python
# BEFORE (lines 179-184):
try:
    new_id = ProductService.create(payload)
except Exception as exc:
    return api_error("VALIDATION_ERROR", str(exc), status=422)

# AFTER:
from ..services.product_service import ProductError

try:
    new_id = ProductService.create(payload)
except ProductError as exc:
    msg = str(exc)
    if "SKU already exists" in msg:
        return api_error("DUPLICATE_SKU", msg, status=409)
    return api_error("VALIDATION_ERROR", msg, status=422)
```

---

### Phase 5: API Layer — DB-009 New Endpoint

#### Step 5.1: Add `create_purchase_order()` endpoint
**File**: `app/routes/api.py` (after line 217, before Suppliers section)
- **Action**: Add new POST `/api/purchase-orders` endpoint with:
  - Rate limiting (30/min like other write endpoints)
  - `@login_required` + `@write_roles_required`
  - Payload validation (po_number, supplier_id, product_id, quantity required)
  - Call `PurchaseOrderRepository.create()` (or create a service if needed)
  - Catch `POError` for unique PO number → 409
  - Audit logging
  - Cache busting (`cache_bust_purchase_orders()`)
- **Why**: DB-009 requires REST API endpoint for PO creation
- **Dependencies**: None (uses existing `PurchaseOrderRepository.create()`)
- **Risk**: Medium — new endpoint, must follow existing patterns
- **Validation**: Test PO creation success (201), duplicate PO number (409), invalid payload (422)

```python
# ADD after delete_product() (line 217):

# ----- Purchase Orders -----
@api_bp.route("/purchase-orders", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
@write_roles_required
def create_purchase_order():
    from ..repositories import PurchaseOrderRepository
    from ..repositories.po_repo import POError
    
    payload = request.get_json(silent=True) or {}
    
    # Validate required fields
    required = ["po_number", "supplier_id", "product_id", "quantity"]
    for field in required:
        if not payload.get(field):
            return api_error("VALIDATION_ERROR", f"Missing required field: {field}", status=422)
    
    try:
        new_id = PurchaseOrderRepository.create(payload)
    except POError as exc:
        msg = str(exc)
        if "already exists" in msg:
            return api_error("DUPLICATE_PO_NUMBER", msg, status=409)
        return api_error("VALIDATION_ERROR", msg, status=422)
    except Exception as exc:
        return api_error("VALIDATION_ERROR", str(exc), status=422)
    
    AuditRepository.record(current_user.id, "api.purchase_order.create",
                           target_type="purchase_order", target_id=new_id,
                           detail={"po_number": payload.get("po_number")})
    cache_bust_purchase_orders()
    return api_response({"id": new_id}, status=201, message="Purchase order created.")
```

---

### Phase 6: Testing (TDD — Write Tests First)

#### Step 6.1: Add test for PO unique violation returns 409
**File**: `tests/test_db_integrity_fixes.py`
- **Action**: Add test function `test_db009_duplicate_po_number_returns_409`
- **Why**: Verify DB-009 endpoint returns correct status code
- **Dependencies**: Step 5.1 (endpoint must exist)
- **Risk**: Low — test only

```python
def test_db009_duplicate_po_number_returns_409(app, client):
    """Duplicate PO number must return 409, not 422."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur)
            supplier_id = cur.execute(
                "INSERT INTO suppliers (name, initials) VALUES ('Test', 'TS') RETURNING id"
            )
            supplier_id = cur.fetchone()["id"]
            
            # Create first PO
            po_number = f"PO-DB009-{RUN}-001"
            cur.execute(
                "INSERT INTO purchase_orders (po_number, supplier_id, product_id, quantity) VALUES (%s, %s, %s, 10)",
                (po_number, supplier_id, product_id)
            )
        
        # Try to create duplicate via API
        payload = {
            "po_number": po_number,
            "supplier_id": supplier_id,
            "product_id": product_id,
            "quantity": 5
        }
        response = client.post("/api/purchase-orders", json=payload)
        assert response.status_code == 409
        data = response.get_json()
        assert data["success"] is False
        assert data["error"]["code"] == "DUPLICATE_PO_NUMBER"
        
        _cleanup_product(product_id)
```

#### Step 6.2: Add test for 409 vs 422 differentiation in product creation
**File**: `tests/test_db_integrity_fixes.py`
- **Action**: Add test function `test_db001_sku_unique_violation_returns_409`
- **Why**: Verify DB-001 fix — unique violation returns 409, validation errors return 422
- **Dependencies**: Step 4.1 (API fix)
- **Risk**: Low — test only

```python
def test_db001_sku_unique_violation_returns_409(app, client):
    """Duplicate SKU must return 409, validation errors return 422."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur)
            cur.execute("SELECT sku FROM products WHERE id = %s", (product_id,))
            sku = cur.fetchone()["sku"]
        
        # Duplicate SKU → 409
        payload = {"sku": sku, "name": "Duplicate", "warehouse": "WH-Test", "unit_price": 1}
        response = client.post("/api/products", json=payload)
        assert response.status_code == 409
        data = response.get_json()
        assert data["error"]["code"] == "DUPLICATE_SKU"
        
        # Invalid payload (missing required) → 422
        payload = {"sku": "NEW-SKU"}  # missing name, warehouse, unit_price
        response = client.post("/api/products", json=payload)
        assert response.status_code == 422
        data = response.get_json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        
        _cleanup_product(product_id)
```

#### Step 6.3: Add test for product edit bypass prevention (DB-021)
**File**: `tests/test_db_integrity_fixes.py`
- **Action**: Add test function `test_db021_product_edit_rejects_current_stock`
- **Why**: Verify PUT `/api/products/<id>` rejects `current_stock` in payload
- **Dependencies**: Steps 1.1, 2.1, 3.1 (all DB-021 changes)
- **Risk**: Low — test only

```python
def test_db021_product_edit_rejects_current_stock(app, client):
    """PUT /api/products/<id> with current_stock must return 422."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur, stock=100)
        
        # Try to update with current_stock in payload
        payload = {"name": "Updated Name", "current_stock": 50}
        response = client.put(f"/api/products/{product_id}", json=payload)
        assert response.status_code == 422
        data = response.get_json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "current_stock" in data["error"]["message"].lower()
        
        # Verify stock unchanged
        with get_cursor() as cur:
            cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
            assert cur.fetchone()["current_stock"] == 100
        
        _cleanup_product(product_id)
```

#### Step 6.4: Add test for successful PO creation
**File**: `tests/test_db_integrity_fixes.py`
- **Action**: Add test function `test_db009_create_purchase_order_success`
- **Why**: Verify happy path for new endpoint
- **Dependencies**: Step 5.1
- **Risk**: Low — test only

```python
def test_db009_create_purchase_order_success(app, client):
    """Valid PO creation returns 201 with ID."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur)
            supplier_id = cur.execute(
                "INSERT INTO suppliers (name, initials) VALUES ('Test', 'TS') RETURNING id"
            )
            supplier_id = cur.fetchone()["id"]
        
        payload = {
            "po_number": f"PO-DB009-{RUN}-NEW",
            "supplier_id": supplier_id,
            "product_id": product_id,
            "quantity": 10,
            "unit_cost": 5.0,
            "status": "draft",
            "eta_date": "2026-12-31"
        }
        response = client.post("/api/purchase-orders", json=payload)
        assert response.status_code == 201
        data = response.get_json()
        assert data["success"] is True
        assert "id" in data["data"]
        assert data["message"] == "Purchase order created."
        
        # Verify in DB
        with get_cursor() as cur:
            cur.execute("SELECT * FROM purchase_orders WHERE id = %s", (data["data"]["id"],))
            po = cur.fetchone()
            assert po["po_number"] == payload["po_number"]
            assert po["quantity"] == 10
        
        _cleanup_product(product_id)
```

---

## Testing Strategy

| Test Type | Target | Coverage |
|-----------|--------|----------|
| **Unit** | `ProductService.validate_payload()` | Rejects `current_stock` in updates |
| **Unit** | `ProductRepository.update()` | Calls `sp_product_update` without `current_stock` |
| **Integration** | `POST /api/products` | Duplicate SKU → 409; invalid payload → 422 |
| **Integration** | `PUT /api/products/<id>` | `current_stock` in payload → 422 |
| **Integration** | `POST /api/purchase-orders` | Success → 201; duplicate PO → 409; invalid → 422 |
| **E2E** | Full PO lifecycle | Create PO → transition to received → stock updated |

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|------|-------------|------------|
| **Stored procedure signature change breaks existing calls** | Other code may call `sp_product_update` with old signature | Grep codebase for `sp_product_update` calls — only `ProductRepository.update()` found |
| **API endpoint conflicts with existing routes** | `/api/purchase-orders` might conflict | Check `api.py` — no existing `/purchase-orders` route |
| **Test flakiness from shared test data** | Tests use same DB, may interfere | Use unique `RUN` prefix per test run; cleanup in `finally` blocks |
| **Missing import for `ProductError`/`POError`** | API route needs imports | Add imports inside function to avoid circular imports (existing pattern) |

---

## Success Criteria

- [ ] All new unit tests pass (`pytest tests/test_db_integrity_fixes.py::test_db021_*`)
- [ ] All new integration tests pass (`pytest tests/test_db_integrity_fixes.py::test_db001_*`, `test_db009_*`)
- [ ] Existing tests still pass (`pytest tests/test_db_integrity_fixes.py`)
- [ ] Full test suite passes (`pytest`)
- [ ] Manual verification:
  - [ ] POST `/api/products` with duplicate SKU → 409
  - [ ] POST `/api/products` with invalid data → 422
  - [ ] PUT `/api/products/<id>` with `current_stock` → 422
  - [ ] POST `/api/purchase-orders` valid → 201
  - [ ] POST `/api/purchase-orders` duplicate PO number → 409
  - [ ] POST `/api/purchase-orders` invalid → 422

---

## Dependencies

- **Internal**: None (all changes within this plan)
- **External**: None
- **Data**: No migrations needed — schema already has unique constraints on `products.sku` and `purchase_orders.po_number`

---

## Rollback Plan

| Component | Rollback Action |
|-----------|-----------------|
| **Database** | Re-run original `sp_product_update` with `p_current_stock` parameter from git history |
| **Code** | Revert `app/routes/api.py`, `app/repositories/product_repo.py`, `app/services/product_service.py` to previous commit |
| **Tests** | Remove added test functions from `tests/test_db_integrity_fixes.py` |

---

## Implementation Order Summary

1. **Write tests first** (Steps 6.1-6.4) — TDD
2. **Database** (Step 1.1) — Update stored procedure
3. **Repository** (Step 2.1) — Update repository call
4. **Service** (Step 3.1) — Update validation
5. **API DB-001** (Step 4.1) — Fix exception handling
6. **API DB-009** (Step 5.1) — Add PO creation endpoint
7. **Run all tests** — Verify everything passes
8. **Manual verification** — Confirm behavior matches requirements