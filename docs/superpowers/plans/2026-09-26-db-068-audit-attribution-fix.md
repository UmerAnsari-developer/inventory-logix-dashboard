# DB-068 Audit Attribution Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix audit attribution so all audit_log entries have proper user_id, eliminate double-audit in API routes.

**Architecture:** Use PostgreSQL GUC `app.current_user_id` set via `SET LOCAL` in each transaction, with a helper function `current_app_user_id()` that triggers call. Flask `before_request` sets `g.user_id`, connection layer injects it per-transaction. API routes remove explicit `AuditRepository.record()` calls since triggers now capture user correctly.

**Tech Stack:** PostgreSQL 14+, Flask 2.x, SQLAlchemy 2.x, psycopg2

**Spec:** Research report on DB-068 (this plan implements its recommendations)

---

## Global Constraints

- All SQL must use parameterized queries (no string concatenation)
- Stored procedures in `app/database/procedures.sql`, triggers in `app/database/triggers.sql`
- Flask routes use blueprints: `api` (REST), `ui` (server-rendered)
- RBAC: `viewer` (read-only), `admin`/`manager` (write) via `@roles_required` / `@write_roles_required`
- Session: browser-session cookie only (no persistent remember cookie)
- API response envelope: `{success: boolean, data: ..., error: ...}`
- Asset version query params in `base.html` must be bumped on JS/CSS changes
- Tests: pytest, 80%+ coverage required (unit, integration, E2E)

---

## Review Focus

| Input / Condition | Expected Behavior | Test Location |
|-------------------|-------------------|---------------|
| Unauthenticated request to API route | `g.user_id` = NULL, trigger uses NULL (or 0 for system), no crash | `tests/test_audit_attribution.py::test_unauthenticated_request` |
| Authenticated viewer (read-only) creates product via UI | `audit_log.user_id` = viewer's ID, single entry | `tests/test_audit_attribution.py::test_viewer_ui_create_product` |
| Authenticated admin creates product via API | `audit_log.user_id` = admin's ID, **exactly one** entry (no double-audit) | `tests/test_audit_attribution.py::test_admin_api_create_product_no_double` |
| Concurrent requests from different users | Each transaction sees only its own `app.current_user_id` | `tests/test_audit_attribution.py::test_concurrent_users_isolation` |
| Trigger fires on direct SQL (psql) | `current_app_user_id()` returns NULL, audit_log.user_id = NULL | `tests/test_audit_attribution.py::test_direct_sql_trigger_null_user` |

---

## File Map

| File | Role | Changes |
|------|------|---------|
| `app/database/triggers.sql` | Trigger definitions | Add `current_app_user_id()` helper; update 4 trigger functions |
| `app/database/procedures.sql` | Stored procedures | (No changes — triggers only) |
| `app/database/connection.py` | DB connection / cursor | `get_cursor()` executes `SET LOCAL app.current_user_id = %s` |
| `app/__init__.py` | Flask app factory | Add `before_request` to set `g.user_id` from session |
| `app/routes/api.py` | REST API routes | Remove 5 explicit `AuditRepository.record()` calls |
| `app/routes/ui.py` | UI routes | Optionally remove redundant audit calls (if any) |
| `app/repositories/audit_repository.py` | Audit data access | (No changes — used by triggers indirectly) |
| `migrations/versions/XXXX_add_app_current_user_id_guc.py` | Alembic migration | Add GUC `app.current_user_id` to PostgreSQL config |
| `tests/test_audit_attribution.py` | New test file | Comprehensive test coverage for attribution |

---

## Implementation Phases

### Phase 1: Database Foundation (GUC + Helper Function + Trigger Updates)

#### Task 1.1: Create Alembic Migration for GUC

**Files:**
- Create: `migrations/versions/20260926_add_app_current_user_id_guc.py`
- Test: `tests/test_audit_attribution.py` (will be created in Phase 3)

**Interfaces:**
- Consumes: None (first task)
- Produces: PostgreSQL GUC `app.current_user_id` available cluster-wide

- [ ] **Step 1: Write the failing test** (in new test file, but runnable after migration)

```python
# tests/test_audit_attribution.py
def test_guc_exists(db_connection):
    """Verify app.current_user_id GUC is defined."""
    with db_connection.cursor() as cur:
        cur.execute("SHOW app.current_user_id;")
        result = cur.fetchone()
    assert result is not None
    # Default should be empty string or NULL
    assert result[0] in ('', None)
```

- [ ] **Step 2: Run test to verify it fails** (migration not applied yet)

```bash
pytest tests/test_audit_attribution.py::test_guc_exists -v
# Expected: FAIL - GUC not defined
```

- [ ] **Step 3: Create migration file**

```python
# migrations/versions/20260926_add_app_current_user_id_guc.py
"""Add app.current_user_id GUC for audit attribution

Revision ID: 20260926_add_app_current_user_id_guc
Revises: <previous_revision_id>
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa

revision = '20260926_add_app_current_user_id_guc'
down_revision = '<previous_revision_id>'  # Replace with actual previous revision
branch_labels = None
depends_on = None

def upgrade():
    # Add custom GUC for current application user ID
    # This is a session-local setting, set via SET LOCAL in each transaction
    op.execute("""
        ALTER SYSTEM SET app.current_user_id = '';
    """)
    # Reload config to make it available immediately (requires superuser)
    # In production, this requires postgresql.conf edit + reload
    # For development, ALTER SYSTEM + pg_reload_conf() works
    op.execute("SELECT pg_reload_conf();")

def downgrade():
    # Remove the GUC setting
    op.execute("ALTER SYSTEM RESET app.current_user_id;")
    op.execute("SELECT pg_reload_conf();")
```

- [ ] **Step 4: Run migration and verify**

```bash
flask db upgrade
pytest tests/test_audit_attribution.py::test_guc_exists -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/20260926_add_app_current_user_id_guc.py tests/test_audit_attribution.py
git commit -m "db: add app.current_user_id GUC for audit attribution (DB-068)"
```

---

#### Task 1.2: Add `current_app_user_id()` Helper Function to triggers.sql

**Files:**
- Modify: `app/database/triggers.sql` (add function at top of file)
- Test: `tests/test_audit_attribution.py`

**Interfaces:**
- Consumes: GUC `app.current_user_id` (from Task 1.1)
- Produces: SQL function `current_app_user_id() RETURNS bigint` usable in triggers

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audit_attribution.py
def test_current_app_user_id_function_exists(db_connection):
    """Verify helper function exists and returns NULL by default."""
    with db_connection.cursor() as cur:
        cur.execute("SELECT current_app_user_id();")
        result = cur.fetchone()
    assert result is not None
    assert result[0] is None  # Default: no user set
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_audit_attribution.py::test_current_app_user_id_function_exists -v
# Expected: FAIL - function not defined
```

- [ ] **Step 3: Add helper function to triggers.sql**

```sql
-- app/database/triggers.sql
-- Add at TOP of file, before any trigger definitions

-- Helper function to safely read app.current_user_id GUC
-- Returns NULL if not set or not a valid integer
CREATE OR REPLACE FUNCTION current_app_user_id() RETURNS bigint
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_user_id text;
    v_result bigint;
BEGIN
    -- current_setting returns the value; NULL if not set
    v_user_id := current_setting('app.current_user_id', true);
    
    IF v_user_id IS NULL OR v_user_id = '' THEN
        RETURN NULL;
    END IF;
    
    -- Validate it's a valid integer (defense against injection)
    BEGIN
        v_result := v_user_id::bigint;
        RETURN v_result;
    EXCEPTION WHEN invalid_text_representation THEN
        RETURN NULL;
    END;
END;
$$;

-- Grant execute to application role (adjust role name as needed)
GRANT EXECUTE ON FUNCTION current_app_user_id() TO inventory_app;
```

- [ ] **Step 4: Apply triggers.sql and verify**

```bash
# Apply updated triggers.sql (run via psql or migration)
psql $DATABASE_URL -f app/database/triggers.sql
pytest tests/test_audit_attribution.py::test_current_app_user_id_function_exists -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add app/database/triggers.sql
git commit -m "db: add current_app_user_id() helper function for audit triggers (DB-068)"
```

---

#### Task 1.3: Update 4 Trigger Functions to Use `current_app_user_id()`

**Files:**
- Modify: `app/database/triggers.sql` (update 4 trigger functions)
- Test: `tests/test_audit_attribution.py`

**Interfaces:**
- Consumes: `current_app_user_id()` function (from Task 1.2)
- Produces: Triggers that insert correct `user_id` into `audit_log`

**Trigger Functions to Update:**
1. `trg_log_product_change` (on `products` table)
2. `trg_log_supplier_change` (on `suppliers` table)
3. `trg_log_movement_create` (on `stock_movements` table)
4. `trg_log_po_change` (on `purchase_orders` table)

- [ ] **Step 1: Write failing tests for each trigger** (4 tests)

```python
# tests/test_audit_attribution.py
import pytest

@pytest.mark.parametrize("table,trigger_name,action", [
    ("products", "trg_log_product_change", "INSERT"),
    ("suppliers", "trg_log_supplier_change", "INSERT"),
    ("stock_movements", "trg_log_movement_create", "INSERT"),
    ("purchase_orders", "trg_log_po_change", "INSERT"),
])
def test_trigger_captures_user_id(db_connection, table, trigger_name, action, authenticated_user):
    """Each trigger should capture current_app_user_id() as user_id."""
    user_id = authenticated_user['id']  # Fixture sets up user and GUC
    
    with db_connection.cursor() as cur:
        # Set GUC for this transaction
        cur.execute("SET LOCAL app.current_user_id = %s;", (str(user_id),))
        
        # Perform action that fires trigger
        if table == "products":
            cur.execute("""
                INSERT INTO products (sku, name, unit_price, reorder_point, reorder_qty)
                VALUES (%s, %s, %s, %s, %s) RETURNING id;
            """, (f"TEST-{user_id}", "Test Product", 10.00, 5, 20))
        elif table == "suppliers":
            cur.execute("""
                INSERT INTO suppliers (name, contact_email, lead_time_days)
                VALUES (%s, %s, %s) RETURNING id;
            """, (f"Test Supplier {user_id}", "test@example.com", 7))
        elif table == "stock_movements":
            # Need a product first
            cur.execute("INSERT INTO products (sku, name, unit_price) VALUES (%s, %s, %s) RETURNING id;",
                       (f"MOV-{user_id}", "Move Product", 15.00))
            prod_id = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO stock_movements (product_id, qty, movement_type, reference)
                VALUES (%s, %s, %s, %s) RETURNING id;
            """, (prod_id, 10, 'IN', 'TEST'))
        elif table == "purchase_orders":
            cur.execute("""
                INSERT INTO purchase_orders (supplier_id, status, expected_date)
                VALUES (1, 'DRAFT', CURRENT_DATE + 7) RETURNING id;
            """)
        
        # Check audit_log
        cur.execute("""
            SELECT user_id FROM audit_log
            WHERE table_name = %s AND action = %s
            ORDER BY created_at DESC LIMIT 1;
        """, (table, action))
        audit = cur.fetchone()
    
    assert audit is not None, f"No audit entry for {table} {action}"
    assert audit[0] == user_id, f"Expected user_id={user_id}, got {audit[0]}"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_audit_attribution.py::test_trigger_captures_user_id -v
# Expected: 4 FAILs - triggers still use NULL or old logic
```

- [ ] **Step 3: Update each trigger function in triggers.sql**

```sql
-- app/database/triggers.sql
-- UPDATE: trg_log_product_change
CREATE OR REPLACE FUNCTION trg_log_product_change() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_log (table_name, record_id, action, old_data, new_data, user_id)
        VALUES ('products', NEW.id, 'INSERT', NULL, to_jsonb(NEW), current_app_user_id());
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO audit_log (table_name, record_id, action, old_data, new_data, user_id)
        VALUES ('products', NEW.id, 'UPDATE', to_jsonb(OLD), to_jsonb(NEW), current_app_user_id());
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO audit_log (table_name, record_id, action, old_data, new_data, user_id)
        VALUES ('products', OLD.id, 'DELETE', to_jsonb(OLD), NULL, current_app_user_id());
    END IF;
    RETURN NEW;
END;
$$;

-- UPDATE: trg_log_supplier_change
CREATE OR REPLACE FUNCTION trg_log_supplier_change() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_log (table_name, record_id, action, old_data, new_data, user_id)
        VALUES ('suppliers', NEW.id, 'INSERT', NULL, to_jsonb(NEW), current_app_user_id());
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO audit_log (table_name, record_id, action, old_data, new_data, user_id)
        VALUES ('suppliers', NEW.id, 'UPDATE', to_jsonb(OLD), to_jsonb(NEW), current_app_user_id());
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO audit_log (table_name, record_id, action, old_data, new_data, user_id)
        VALUES ('suppliers', OLD.id, 'DELETE', to_jsonb(OLD), NULL, current_app_user_id());
    END IF;
    RETURN NEW;
END;
$$;

-- UPDATE: trg_log_movement_create
CREATE OR REPLACE FUNCTION trg_log_movement_create() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    -- Only log INSERT (movements are immutable)
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_log (table_name, record_id, action, old_data, new_data, user_id)
        VALUES ('stock_movements', NEW.id, 'INSERT', NULL, to_jsonb(NEW), current_app_user_id());
    END IF;
    RETURN NEW;
END;
$$;

-- UPDATE: trg_log_po_change
CREATE OR REPLACE FUNCTION trg_log_po_change() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_log (table_name, record_id, action, old_data, new_data, user_id)
        VALUES ('purchase_orders', NEW.id, 'INSERT', NULL, to_jsonb(NEW), current_app_user_id());
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO audit_log (table_name, record_id, action, old_data, new_data, user_id)
        VALUES ('purchase_orders', NEW.id, 'UPDATE', to_jsonb(OLD), to_jsonb(NEW), current_app_user_id());
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO audit_log (table_name, record_id, action, old_data, new_data, user_id)
        VALUES ('purchase_orders', OLD.id, 'DELETE', to_jsonb(OLD), NULL, current_app_user_id());
    END IF;
    RETURN NEW;
END;
$$;
```

- [ ] **Step 4: Apply triggers.sql and verify**

```bash
psql $DATABASE_URL -f app/database/triggers.sql
pytest tests/test_audit_attribution.py::test_trigger_captures_user_id -v
# Expected: 4 PASS
```

- [ ] **Step 5: Commit**

```bash
git add app/database/triggers.sql
git commit -m "db: update 4 audit triggers to use current_app_user_id() (DB-068)"
```

---

### Phase 2: Flask Application Layer (Connection + before_request)

#### Task 2.1: Modify `get_cursor()` in `connection.py` to Set GUC

**Files:**
- Modify: `app/database/connection.py` (function `get_cursor()`)
- Test: `tests/test_audit_attribution.py`

**Interfaces:**
- Consumes: `g.user_id` set by `before_request` (Task 2.2)
- Produces: Database cursor with `SET LOCAL app.current_user_id` executed

- [ ] **Step 1: Write failing test**

```python
# tests/test_audit_attribution.py
def test_get_cursor_sets_guc(app, db_connection, authenticated_user):
    """get_cursor() should execute SET LOCAL app.current_user_id."""
    with app.app_context():
        from app.database.connection import get_cursor
        from flask import g
        g.user_id = authenticated_user['id']
        
        with get_cursor() as cur:
            cur.execute("SHOW app.current_user_id;")
            result = cur.fetchone()
        
        assert result[0] == str(authenticated_user['id'])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_audit_attribution.py::test_get_cursor_sets_guc -v
# Expected: FAIL - get_cursor doesn't set GUC yet
```

- [ ] **Step 3: Modify `get_cursor()` in connection.py**

```python
# app/database/connection.py
from flask import g, has_app_context
import psycopg2
from contextlib import contextmanager

@contextmanager
def get_cursor(commit: bool = False):
    """Get a database cursor with automatic transaction handling.
    
    Sets app.current_user_id GUC for audit attribution if user is authenticated.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Set GUC for audit attribution (transaction-local)
            if has_app_context() and hasattr(g, 'user_id') and g.user_id is not None:
                cur.execute("SET LOCAL app.current_user_id = %s;", (str(g.user_id),))
            yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        # Connection returned to pool (or closed if not pooled)
        pass
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_audit_attribution.py::test_get_cursor_sets_guc -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add app/database/connection.py
git commit -m "db: set app.current_user_id GUC in get_cursor() for audit attribution (DB-068)"
```

---

#### Task 2.2: Add `before_request` Handler to Set `g.user_id`

**Files:**
- Modify: `app/__init__.py` (in `create_app()` function)
- Test: `tests/test_audit_attribution.py`

**Interfaces:**
- Consumes: Flask session / `current_user` from Flask-Login
- Produces: `g.user_id` available for `get_cursor()`

- [ ] **Step 1: Write failing test**

```python
# tests/test_audit_attribution.py
def test_before_request_sets_g_user_id(app, client, authenticated_user):
    """before_request should set g.user_id from current_user."""
    with app.test_client() as c:
        # Login first
        c.post('/auth/login', data={
            'username': authenticated_user['username'],
            'password': 'testpass'
        })
        
        # Make a request
        response = c.get('/api/products')
        
        # g.user_id should be set during request
        # We verify indirectly via audit log in integration test
        assert response.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_audit_attribution.py::test_before_request_sets_g_user_id -v
# Expected: FAIL - before_request not implemented
```

- [ ] **Step 3: Add before_request to app/__init__.py**

```python
# app/__init__.py
from flask import g
from flask_login import current_user

def create_app(config_class=Config):
    app = Flask(__name__)
    # ... existing config ...
    
    # ... existing extensions init ...
    
    @app.before_request
    def set_current_user_id():
        """Set g.user_id for audit attribution in database layer."""
        if current_user.is_authenticated:
            g.user_id = current_user.id
        else:
            g.user_id = None
    
    # ... register blueprints ...
    
    return app
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_audit_attribution.py::test_before_request_sets_g_user_id -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add app/__init__.py
git commit -m "flask: set g.user_id in before_request for audit attribution (DB-068)"
```

---

### Phase 3: Remove Double-Audit from API Routes

#### Task 3.1: Remove Explicit `AuditRepository.record()` Calls from `api.py`

**Files:**
- Modify: `app/routes/api.py` (5 locations)
- Test: `tests/test_audit_attribution.py`

**Routes to Fix (5 total):**
1. `create_product` (POST /api/products)
2. `update_product` (PUT /api/products/<id>)
3. `delete_product` (DELETE /api/products/<id>)
4. `create_supplier` (POST /api/suppliers)
5. `create_purchase_order` (POST /api/purchase-orders)

**Interfaces:**
- Consumes: Triggers now handle audit logging with correct user_id
- Produces: Single audit entry per operation (no duplicates)

- [ ] **Step 1: Write failing test (verifies no double-audit)**

```python
# tests/test_audit_attribution.py
def test_api_create_product_no_double_audit(app, client, authenticated_admin):
    """API create_product should create exactly ONE audit entry."""
    with app.test_client() as c:
        # Login as admin
        c.post('/auth/login', data={
            'username': authenticated_admin['username'],
            'password': 'adminpass'
        })
        
        # Count audit entries before
        with app.app_context():
            from app.database.connection import get_cursor
            with get_cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM audit_log WHERE table_name = 'products';")
                before_count = cur.fetchone()[0]
        
        # Create product via API
        response = c.post('/api/products', json={
            'sku': 'API-TEST-001',
            'name': 'API Test Product',
            'unit_price': 25.00,
            'reorder_point': 10,
            'reorder_qty': 50
        })
        assert response.status_code == 201
        
        # Count audit entries after
        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM audit_log WHERE table_name = 'products';")
                after_count = cur.fetchone()[0]
        
        # Should be exactly +1 (trigger only, no explicit AuditRepository call)
        assert after_count == before_count + 1, f"Expected +1 audit entry, got +{after_count - before_count}"
```

- [ ] **Step 2: Run test to verify it fails (double-audit currently happens)**

```bash
pytest tests/test_audit_attribution.py::test_api_create_product_no_double_audit -v
# Expected: FAIL - audit count increases by 2 (trigger + explicit)
```

- [ ] **Step 3: Remove explicit audit calls from each route**

```python
# app/routes/api.py

# 1. create_product - REMOVE these lines:
# from app.repositories.audit_repository import AuditRepository
# ...
# AuditRepository.record('products', product.id, 'CREATE', None, product_data, current_user.id)

@api_bp.route('/products', methods=['POST'])
@write_roles_required
def create_product():
    data = request.get_json()
    # ... validation ...
    product = ProductService.create_product(data)
    # REMOVED: AuditRepository.record(...)
    return jsonify(success=True, data=product.to_dict()), 201

# 2. update_product - REMOVE AuditRepository.record call
@api_bp.route('/products/<int:product_id>', methods=['PUT'])
@write_roles_required
def update_product(product_id):
    data = request.get_json()
    # ... validation ...
    product = ProductService.update_product(product_id, data)
    # REMOVED: AuditRepository.record(...)
    return jsonify(success=True, data=product.to_dict())

# 3. delete_product - REMOVE AuditRepository.record call
@api_bp.route('/products/<int:product_id>', methods=['DELETE'])
@write_roles_required
def delete_product(product_id):
    ProductService.delete_product(product_id)
    # REMOVED: AuditRepository.record(...)
    return jsonify(success=True, message='Product deleted')

# 4. create_supplier - REMOVE AuditRepository.record call
@api_bp.route('/suppliers', methods=['POST'])
@write_roles_required
def create_supplier():
    data = request.get_json()
    # ... validation ...
    supplier = SupplierService.create_supplier(data)
    # REMOVED: AuditRepository.record(...)
    return jsonify(success=True, data=supplier.to_dict()), 201

# 5. create_purchase_order - REMOVE AuditRepository.record call
@api_bp.route('/purchase-orders', methods=['POST'])
@write_roles_required
def create_purchase_order():
    data = request.get_json()
    # ... validation ...
    po = PurchaseOrderService.create_purchase_order(data)
    # REMOVED: AuditRepository.record(...)
    return jsonify(success=True, data=po.to_dict()), 201
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_audit_attribution.py::test_api_create_product_no_double_audit -v
# Expected: PASS
```

- [ ] **Step 5: Add similar tests for other 4 routes and verify**

```bash
# Add tests for update_product, delete_product, create_supplier, create_purchase_order
pytest tests/test_audit_attribution.py -k "no_double_audit" -v
# Expected: 5 PASS
```

- [ ] **Step 6: Commit**

```bash
git add app/routes/api.py tests/test_audit_attribution.py
git commit -m "api: remove double-audit from 5 routes, triggers now handle attribution (DB-068)"
```

---

#### Task 3.2: (Optional) Remove Redundant Audit Calls from `ui.py`

**Files:**
- Modify: `app/routes/ui.py` (if any explicit audit calls exist)
- Test: `tests/test_audit_attribution.py`

**Note:** Research indicates UI routes "rely only on triggers (NULL user_id)" — they likely don't have explicit audit calls. Verify and remove if any exist.

- [ ] **Step 1: Search for AuditRepository usage in ui.py**

```bash
grep -n "AuditRepository" app/routes/ui.py
```

- [ ] **Step 2: If found, write test and remove (similar to Task 3.1)**

```python
# tests/test_audit_attribution.py
def test_ui_create_product_single_audit(app, client, authenticated_user):
    """UI create_product should create exactly ONE audit entry via trigger."""
    # Similar to API test but using UI route
    pass
```

- [ ] **Step 3: Commit if changes made**

```bash
git add app/routes/ui.py
git commit -m "ui: remove redundant audit calls, triggers handle attribution (DB-068)"
```

---

### Phase 4: Comprehensive Testing & Validation

#### Task 4.1: Integration Tests for Full Flow

**Files:**
- Test: `tests/test_audit_attribution.py` (add integration tests)

- [ ] **Step 1: Write integration tests covering all scenarios**

```python
# tests/test_audit_attribution.py

def test_full_flow_api_create_update_delete(app, client, authenticated_admin):
    """Complete CRUD cycle via API produces correct audit trail."""
    with app.test_client() as c:
        c.post('/auth/login', data={'username': authenticated_admin['username'], 'password': 'adminpass'})
        
        # CREATE
        resp = c.post('/api/products', json={'sku': 'FLOW-001', 'name': 'Flow Test', 'unit_price': 10.0})
        assert resp.status_code == 201
        product_id = resp.get_json()['data']['id']
        
        # UPDATE
        resp = c.put(f'/api/products/{product_id}', json={'name': 'Flow Test Updated'})
        assert resp.status_code == 200
        
        # DELETE
        resp = c.delete(f'/api/products/{product_id}')
        assert resp.status_code == 200
        
        # Verify audit trail: 3 entries (INSERT, UPDATE, DELETE), all with correct user_id
        with app.app_context():
            from app.database.connection import get_cursor
            with get_cursor() as cur:
                cur.execute("""
                    SELECT action, user_id FROM audit_log
                    WHERE table_name = 'products' AND record_id = %s
                    ORDER BY created_at;
                """, (product_id,))
                audits = cur.fetchall()
        
        assert len(audits) == 3
        actions = [a[0] for a in audits]
        assert actions == ['INSERT', 'UPDATE', 'DELETE']
        for _, uid in audits:
            assert uid == authenticated_admin['id']

def test_full_flow_ui_create_product(app, client, authenticated_user):
    """UI product creation creates audit entry with correct user_id."""
    with app.test_client() as c:
        c.post('/auth/login', data={'username': authenticated_user['username'], 'password': 'userpass'})
        
        # Submit UI form
        resp = c.post('/products/create', data={
            'sku': 'UI-TEST-001',
            'name': 'UI Test Product',
            'unit_price': '15.00',
            'reorder_point': '5',
            'reorder_qty': '20'
        }, follow_redirects=True)
        assert resp.status_code == 200
        
        # Verify audit entry
        with app.app_context():
            from app.database.connection import get_cursor
            with get_cursor() as cur:
                cur.execute("""
                    SELECT user_id FROM audit_log
                    WHERE table_name = 'products' AND action = 'INSERT'
                    ORDER BY created_at DESC LIMIT 1;
                """)
                audit = cur.fetchone()
        
        assert audit[0] == authenticated_user['id']

def test_concurrent_users_isolation(app, db_connection):
    """Concurrent transactions from different users don't leak user_id."""
    import threading
    import time
    
    results = {}
    
    def worker(user_id, results_dict, key):
        with app.app_context():
            from app.database.connection import get_cursor
            from flask import g
            g.user_id = user_id
            
            with get_cursor() as cur:
                cur.execute("SET LOCAL app.current_user_id = %s;", (str(user_id),))
                cur.execute("SELECT current_app_user_id();")
                results_dict[key] = cur.fetchone()[0]
    
    t1 = threading.Thread(target=worker, args=(1, results, 'user1'))
    t2 = threading.Thread(target=worker, args=(2, results, 'user2'))
    t1.start(); t2.start()
    t1.join(); t2.join()
    
    assert results['user1'] == 1
    assert results['user2'] == 2

def test_unauthenticated_request_audit_null_user(app, client):
    """Unauthenticated requests should have NULL user_id in audit (or system user)."""
    with app.test_client() as c:
        # No login
        resp = c.post('/api/products', json={'sku': 'ANON-001', 'name': 'Anon', 'unit_price': 1.0})
        # Should be 401 Unauthorized (write_roles_required)
        assert resp.status_code == 401
        
        # If any audit entry created (e.g., failed attempt logging), user_id should be NULL
        with app.app_context():
            from app.database.connection import get_cursor
            with get_cursor() as cur:
                cur.execute("""
                    SELECT user_id FROM audit_log
                    WHERE table_name = 'products' AND action = 'INSERT'
                    ORDER BY created_at DESC LIMIT 1;
                """)
                audit = cur.fetchone()
        
        # Either no audit entry (blocked by auth) or NULL user_id
        if audit:
            assert audit[0] is None
```

- [ ] **Step 2: Run all integration tests**

```bash
pytest tests/test_audit_attribution.py -v
# Expected: All PASS
```

- [ ] **Step 3: Run full test suite to check for regressions**

```bash
pytest -x --tb=short
# Expected: All existing tests PASS
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_audit_attribution.py
git commit -m "test: add comprehensive audit attribution tests (DB-068)"
```

---

#### Task 4.2: Manual Verification Checklist

- [ ] **Manual Test 1:** Login as admin → Create product via API → Check `audit_log` has 1 entry with admin's user_id
- [ ] **Manual Test 2:** Login as admin → Update product via API → Check `audit_log` has UPDATE entry with admin's user_id
- [ ] **Manual Test 3:** Login as admin → Delete product via API → Check `audit_log` has DELETE entry with admin's user_id
- [ ] **Manual Test 4:** Login as viewer → Create product via UI → Check `audit_log` has INSERT entry with viewer's user_id
- [ ] **Manual Test 5:** Login as manager → Create supplier via API → Check `audit_log` has entry with manager's user_id
- [ ] **Manual Test 6:** Login as admin → Create purchase order via API → Check `audit_log` has entry with admin's user_id
- [ ] **Manual Test 7:** Direct SQL insert (psql) → Check `audit_log.user_id` is NULL (no Flask context)
- [ ] **Manual Test 8:** Verify no duplicate audit entries for any operation

---

### Phase 5: Documentation & Cleanup

#### Task 5.1: Update Documentation

**Files:**
- Modify: `README.md` (if audit system documented)
- Modify: `docs/architecture.md` (if exists)

- [ ] **Step 1: Document the audit attribution mechanism**

```markdown
# Audit Attribution System (DB-068)

All audit_log entries now capture the authenticated user via PostgreSQL GUC `app.current_user_id`.

## How It Works

1. Flask `before_request` sets `g.user_id` from `current_user.id`
2. `get_cursor()` executes `SET LOCAL app.current_user_id = <user_id>` per transaction
3. Trigger functions call `current_app_user_id()` to read the GUC
4. Audit entries automatically include correct `user_id`

## API Routes

API routes no longer call `AuditRepository.record()` explicitly — triggers handle it.

## Direct Database Access

Direct SQL (psql, scripts) will have `user_id = NULL` in audit_log (expected).
```

- [ ] **Step 2: Commit**

```bash
git add README.md docs/architecture.md
git commit -m "docs: document audit attribution mechanism (DB-068)"
```

---

## Migration Strategy

### Deployment Order

1. **Deploy migration** (Task 1.1) — Adds GUC to PostgreSQL
   - Run `flask db upgrade` on target environment
   - Verify with `SHOW app.current_user_id;`

2. **Deploy trigger updates** (Tasks 1.2, 1.3) — Apply updated `triggers.sql`
   - Run `psql $DATABASE_URL -f app/database/triggers.sql`
   - Verify triggers use `current_app_user_id()`

3. **Deploy Flask changes** (Tasks 2.1, 2.2, 3.1) — Code changes
   - Restart Flask application
   - `before_request` sets `g.user_id`
   - `get_cursor()` sets GUC
   - API routes no longer double-audit

4. **Run tests** (Task 4.1) — Validate in staging
   - Full test suite passes
   - Manual verification checklist passes

### Rollback Plan

| Component | Rollback Action |
|-----------|-----------------|
| GUC (migration) | `flask db downgrade` (runs `downgrade()` removing GUC) |
| Triggers | `psql $DATABASE_URL -f app/database/triggers.sql.rollback` (keep backup) |
| Flask code | `git revert <commit-hash>` for each commit; restart app |
| Tests | `git revert <test-commit>` |

**Rollback Verification:**
- After rollback, audit_log.user_id will be NULL for new entries (old behavior)
- Double-audit returns in API routes (explicit calls restored)
- No data loss — audit_log table unchanged

---

## Risk Assessment & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| GUC not available in managed PG (RDS, Cloud SQL) | Medium | High | Use `SET LOCAL` without `ALTER SYSTEM`; set via `postgresql.conf` or parameter group |
| `SET LOCAL` not executed (connection pooling issue) | Low | High | Verify `get_cursor()` called for every DB operation; add integration test |
| Trigger function error crashes transaction | Low | Medium | `current_app_user_id()` has exception handling; returns NULL on error |
| Double-audit not fully removed (missed route) | Medium | Medium | Grep for `AuditRepository.record` across codebase; test all write routes |
| `g.user_id` not set for background jobs/CLI | Medium | Low | Document: CLI/scripts must manually set `g.user_id` or use `SET LOCAL` directly |
| Performance overhead of `SET LOCAL` per transaction | Low | Low | Negligible (single lightweight SET command); monitor if needed |

---

## Success Criteria

- [ ] All unit tests pass (`pytest tests/test_audit_attribution.py -v`)
- [ ] All integration tests pass (full test suite `pytest`)
- [ ] No double-audit: each API write creates exactly 1 audit entry
- [ ] UI writes create audit entries with correct user_id
- [ ] Unauthenticated/direct SQL creates audit entries with NULL user_id
- [ ] Concurrent users isolated (no user_id leakage)
- [ ] Security review passes (no SQL injection, proper parameterization)
- [ ] Performance: no measurable latency increase on write operations
- [ ] Documentation updated
- [ ] Migration tested on staging with production-like data volume

---

## Dependencies

- **Internal:** Flask-Login for `current_user`, existing `audit_log` table, trigger infrastructure
- **External:** PostgreSQL 14+ (for `SET LOCAL` GUC support), psycopg2
- **Data:** No data migration needed (schema-only changes)

---

## Rollback Plan (Detailed)

### Database Rollback

```bash
# 1. Revert triggers to previous version
psql $DATABASE_URL -f app/database/triggers.sql.backup

# 2. Downgrade migration (removes GUC)
flask db downgrade  # Reverts to previous revision

# 3. Verify
psql $DATABASE_URL -c "SHOW app.current_user_id;"  # Should error: unrecognized parameter
```

### Code Rollback

```bash
# Revert Flask changes (3 commits)
git revert HEAD~3..HEAD  # Adjust range as needed

# Restart application
systemctl restart inventory-app  # or docker-compose restart
```

### Verification After Rollback

- API routes double-audit again (explicit + trigger)
- UI routes have NULL user_id in audit_log
- No application errors

---

## Implementation Order Summary

| Phase | Task | Description | Est. Time |
|-------|------|-------------|-----------|
| 1 | 1.1 | Alembic migration for GUC | 30 min |
| 1 | 1.2 | Add `current_app_user_id()` helper | 20 min |
| 1 | 1.3 | Update 4 trigger functions | 45 min |
| 2 | 2.1 | Modify `get_cursor()` to SET LOCAL | 20 min |
| 2 | 2.2 | Add `before_request` for `g.user_id` | 15 min |
| 3 | 3.1 | Remove 5 explicit audit calls from api.py | 30 min |
| 3 | 3.2 | (Optional) Clean ui.py audit calls | 15 min |
| 4 | 4.1 | Write & run comprehensive tests | 60 min |
| 4 | 4.2 | Manual verification | 30 min |
| 5 | 5.1 | Update documentation | 15 min |
| **Total** | | | **~4.5 hours** |

---

## Notes for Implementer

1. **Run tests after EACH task** — don't batch. The TDD cycle catches issues early.
2. **Backup triggers.sql** before modifying: `cp app/database/triggers.sql app/database/triggers.sql.backup`
3. **Managed PostgreSQL (RDS/Cloud SQL):** You cannot run `ALTER SYSTEM`. Instead:
   - Add `app.current_user_id = ''` to parameter group / postgresql.conf
   - Restart instance (or use `pg_reload_conf()` if superuser)
   - Migration `upgrade()` should handle this gracefully (check if GUC exists first)
4. **Connection pooling:** `SET LOCAL` lasts only for the transaction. PgBouncer transaction pooling is compatible. Session pooling requires `SET` (not LOCAL) but that leaks across requests — **use transaction pooling**.
5. **Flask-Login:** Ensure `current_user.id` returns integer user ID. If using UUID, adjust `current_app_user_id()` to return `uuid` type.
6. **Asset versions:** If you modify any JS/CSS, bump version in `base.html` (e.g., `style.css?v=20.4`).