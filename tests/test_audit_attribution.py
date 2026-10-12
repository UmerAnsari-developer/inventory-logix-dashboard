"""Audit attribution tests — verify user_id is correctly captured in audit_log.

These tests validate the GUC-based audit attribution mechanism:
- app.current_user_id GUC exists and is set per-transaction
- current_app_user_id() helper function returns the GUC value
- All 4 audit triggers (products, suppliers, movements, purchase_orders) capture user_id
- get_cursor() sets the GUC from Flask's g.user_id
- before_request sets g.user_id from current_user
- API and UI flows produce exactly one audit entry per operation
- Concurrent users don't leak user_id across transactions
- Unauthenticated requests result in NULL user_id in audit_log
"""
from __future__ import annotations

import threading
import uuid
from unittest.mock import patch

import pytest

from app.database import get_cursor
from app.repositories import AuditRepository


from app.repositories import UserRepository


@pytest.fixture
def admin_user_id(app):
    """Get the admin user ID dynamically (avoids hardcoded ID=1)."""
    with app.app_context():
        admin = UserRepository.find_by_username("admin")
        assert admin is not None, "admin user must exist"
        return admin.id


RUN = uuid.uuid4().hex[:8].upper()
RUN = uuid.uuid4().hex[:8].upper()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _mk_product(cur, *, stock: int = 0, on_order: int = 0) -> int:
    sku = f"AT-{RUN}-{uuid.uuid4().hex[:6].upper()}"
    cur.execute(
        """
        INSERT INTO products (sku, name, category, warehouse, current_stock,
                              reorder_point, unit_price, on_order)
        VALUES (%s, %s, 'AuditTest', 'WH-Test', %s, 5, 10.0, %s)
        RETURNING id
        """,
        (sku, f"Audit test {sku}", stock, on_order),
    )
    return cur.fetchone()["id"]


def _mk_supplier(cur) -> int:
    token = uuid.uuid4().hex[:8]
    cur.execute(
        """
        INSERT INTO suppliers (name, initials, location, lead_days)
        VALUES (%s, %s, 'Test', 3)
        RETURNING id
        """,
        (f"Audit Supplier {token}", f"AS{token[:3].upper()}"),
    )
    return cur.fetchone()["id"]


def _cleanup_product(product_id: int) -> None:
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM products WHERE id = %s", (product_id,))


def _cleanup_supplier(supplier_id: int) -> None:
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM suppliers WHERE id = %s", (supplier_id,))


# ---------------------------------------------------------------------------
# 1. GUC existence
# ---------------------------------------------------------------------------

def test_guc_exists(app):
    """Verify app.current_user_id GUC can be used in PostgreSQL.
    
    Custom GUCs set via connection options (-c) or set_config() are session-local
    and don't appear in pg_settings. We verify by using current_setting().
    """
    with app.app_context():
        with get_cursor() as cur:
            # Verify GUC can be read (returns empty string by default from -c option)
            cur.execute("SELECT current_setting('app.current_user_id', true)")
            result = cur.fetchone()
            assert result is not None, "GUC app.current_user_id not accessible"
            # Default value from -c option should be empty string
            assert result["current_setting"] == "", f"Expected empty string, got {result['current_setting']}"


# ---------------------------------------------------------------------------
# 2. Helper function
# ---------------------------------------------------------------------------

def test_current_app_user_id_function_exists(app):
    """Verify current_app_user_id() helper function exists and returns NULL by default."""
    with app.app_context():
        with get_cursor() as cur:
            # Function should exist
            cur.execute(
                """
                SELECT 1 FROM pg_proc
                WHERE proname = 'current_app_user_id'
                """
            )
            assert cur.fetchone(), "current_app_user_id() function not defined"

            # Should return NULL when GUC not set
            cur.execute("SELECT current_app_user_id()")
            result = cur.fetchone()
            assert result["current_app_user_id"] is None, (
                f"current_app_user_id() should return NULL by default, got {result}"
            )


# ---------------------------------------------------------------------------
# 3. Triggers capture user_id (parametrized for 4 triggers)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "table,trigger_name,operation,setup_fn,expected_action",
    [
        (
            "products",
            "trg_product_audit",
            "INSERT",
            lambda cur: _mk_product(cur),
            "product_created",
        ),
        (
            "suppliers",
            "trg_supplier_audit",
            "INSERT",
            lambda cur: _mk_supplier(cur),
            "supplier_created",
        ),
        (
            "movements",
            "trg_movement_stock_update",
            "INSERT",
            lambda cur: _mk_movement(cur, admin_user_id),
            "movement_out",
        ),
        (
            "purchase_orders",
            "trg_po_audit",
            "INSERT",
            lambda cur: _mk_po(cur, _mk_product(cur), qty=5),
            "po_created",
        ),
    ],
)
def test_trigger_captures_user_id(app, admin_user_id, table, trigger_name, operation, setup_fn, expected_action):
    """Each audit trigger should capture current_app_user_id() as user_id."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            # Set a known user_id via GUC (use set_config for custom GUC)
            test_user_id = admin_user_id
            cur.execute("SELECT set_config('app.current_user_id', %s, true)", (str(admin_user_id),))

            # Perform the operation that fires the trigger
            target_id = setup_fn(cur)

            # Verify audit_log has the correct user_id
            cur.execute(
                """
                SELECT user_id, action FROM audit_log
                WHERE target_type = %s AND target_id = %s
                ORDER BY created_at DESC LIMIT 1
                """,
                (table.rstrip("s"), target_id),  # target_type is singular
            )
            row = cur.fetchone()
            assert row is not None, f"No audit entry for {table} {operation}"
            assert row["user_id"] == admin_user_id, (
                f"Trigger {trigger_name} did not capture user_id: expected {admin_user_id}, got {row['user_id']}"
            )
            assert row["action"] == expected_action, f"Unexpected action: {row['action']}"


def _mk_movement(cur, admin_user_id) -> int:
    """Create a test movement and return its ID."""
    product_id = _mk_product(cur, stock=10)
    cur.execute(
        """
        INSERT INTO movements (product_id, type, quantity, reference, notes, user_id)
        VALUES (%s, 'OUT', 3, 'TEST-MOV', 'Test movement', NULL)
        RETURNING id
        """,
        (product_id,),
    )
    return cur.fetchone()["id"]


def _mk_po(cur, product_id: int, *, qty: int) -> str:
    po_number = f"PO-AT-{RUN}-{uuid.uuid4().hex[:6].upper()}"
    # supplier_id is NOT NULL (db_integrity d548499a4a0d) — pick an existing
    # supplier, creating one only if the table is empty.
    cur.execute("SELECT id FROM suppliers ORDER BY id LIMIT 1")
    row = cur.fetchone()
    if row:
        supplier_id = row["id"]
    else:
        cur.execute(
            """
            INSERT INTO suppliers (name, initials, location, lead_days)
            VALUES ('Audit Supplier', 'AS', 'Test', 3)
            RETURNING id
            """
        )
        supplier_id = cur.fetchone()["id"]
    cur.execute(
        """
        INSERT INTO purchase_orders (po_number, product_id, supplier_id, quantity, unit_cost, status)
        VALUES (%s, %s, %s, %s, 5.0, 'draft')
        RETURNING id
        """,
        (po_number, product_id, supplier_id, qty),
    )
    return cur.fetchone()["id"]


# ---------------------------------------------------------------------------
# 4. get_cursor() sets GUC
# ---------------------------------------------------------------------------

def test_get_cursor_sets_guc(app):
    """get_cursor() should execute SET LOCAL app.current_user_id from g.user_id."""
    with app.app_context():
        from flask import g

        # Simulate a request context with g.user_id set
        g.user_id = 42

        with get_cursor() as cur:
            # The GUC should be set for this transaction
            cur.execute("SHOW app.current_user_id")
            result = cur.fetchone()
            assert result["app.current_user_id"] == "42", (
                f"GUC not set by get_cursor: expected '42', got '{result['app.current_user_id']}'"
            )


# ---------------------------------------------------------------------------
# 5. before_request sets g.user_id
# ---------------------------------------------------------------------------

def test_before_request_sets_g_user_id(app, auth_client):
    """before_request should set g.user_id from current_user."""
    with app.app_context():
        from flask import g

        # Make a request to trigger before_request (auth_client is already logged in)
        resp = auth_client.get("/")
        assert resp.status_code == 200

        # g.user_id should be set to the authenticated user's id
        assert hasattr(g, "user_id"), "g.user_id not set by before_request"
        assert g.user_id is not None, "g.user_id should not be None for authenticated user"


# ---------------------------------------------------------------------------
# 6. API create_product - no double audit
# ---------------------------------------------------------------------------

def test_api_create_product_no_double_audit(app, auth_client):
    """API create_product should create exactly ONE audit entry (not two)."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            # Clean up any existing audit entries for this test
            cur.execute("DELETE FROM audit_log WHERE action = 'api.product.create'")

    payload = {
        "sku": f"AT-API-{RUN}-{uuid.uuid4().hex[:6].upper()}",
        "name": "API Audit Test Product",
        "warehouse": "WH-Test",
        "unit_price": 10.0,
    }

    # Create via API
    resp = auth_client.post("/api/products", json=payload)
    assert resp.status_code == 201, f"Create failed: {resp.get_json()}"
    product_id = resp.get_json()["data"]["id"]

    with app.app_context():
        with get_cursor() as cur:
            # Count audit entries for this product creation
            cur.execute(
                """
                SELECT COUNT(*) AS c FROM audit_log
                WHERE target_type = 'product' AND target_id = %s
                  AND action IN ('product_created', 'api.product.create')
                """,
                (product_id,),
            )
            count = cur.fetchone()["c"]
            assert count == 1, (
                f"Expected exactly 1 audit entry, got {count}. "
                "Double audit detected: trigger + explicit AuditRepository.record"
            )

            # Verify the audit entry has correct user_id (from authenticated admin)
            cur.execute(
                """
                SELECT user_id, action FROM audit_log
                WHERE target_type = 'product' AND target_id = %s
                ORDER BY created_at DESC LIMIT 1
                """,
                (product_id,),
            )
            row = cur.fetchone()
            assert row["user_id"] is not None, "Audit entry should have user_id"
            assert row["action"] in ("product_created", "api.product.create")

    # Cleanup
    with app.app_context():
        _cleanup_product(product_id)


# ---------------------------------------------------------------------------
# 7. Full flow API CRUD cycle
# ---------------------------------------------------------------------------

def test_full_flow_api_create_update_delete(app, auth_client):
    """Complete CRUD cycle via API produces correct audit trail."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("DELETE FROM audit_log WHERE action LIKE 'api.product.%'")
            # Create a supplier for the test
            cur.execute(
                "INSERT INTO suppliers (name, initials, location, lead_days) VALUES ('Test Supplier', 'TS', 'Test', 3) RETURNING id"
            )
            supplier_id = cur.fetchone()["id"]

    sku = f"AT-CRUD-{RUN}-{uuid.uuid4().hex[:6].upper()}"
    payload = {"sku": sku, "name": "CRUD Test", "warehouse": "WH-Test", "unit_price": 10.0, "supplier_id": supplier_id}

    # CREATE
    resp = auth_client.post("/api/products", json=payload)
    assert resp.status_code == 201
    product_id = resp.get_json()["data"]["id"]

    # UPDATE - need to provide all required fields
    resp = auth_client.put(f"/api/products/{product_id}", json={
        "name": "CRUD Updated",
        "warehouse": "WH-Test",
        "unit_price": 10.0,
        "supplier_id": supplier_id,
        "reorder_point": 5,
    })
    assert resp.status_code == 200, f"Update failed: {resp.get_json()}"

    # DELETE
    resp = auth_client.delete(f"/api/products/{product_id}")
    assert resp.status_code == 204

    with app.app_context():
        with get_cursor() as cur:
            # Should have exactly 3 audit entries: create, update, delete
            cur.execute(
                """
                SELECT action, user_id FROM audit_log
                WHERE target_type = 'product' AND target_id = %s
                ORDER BY created_at
                """,
                (product_id,),
            )
            rows = cur.fetchall()
            assert len(rows) == 3, f"Expected 3 audit entries, got {len(rows)}: {rows}"

            actions = [r["action"] for r in rows]
            assert "api.product.create" in actions or "product_created" in actions
            assert "api.product.update" in actions or "product_updated" in actions
            assert "api.product.delete" in actions or "product_deleted" in actions

            # All should have the same user_id (the authenticated admin)
            user_ids = {r["user_id"] for r in rows}
            assert len(user_ids) == 1, f"All audit entries should have same user_id, got {user_ids}"
            assert None not in user_ids, "Audit entries should not have NULL user_id"


# ---------------------------------------------------------------------------
# 8. Full flow UI create product
# ---------------------------------------------------------------------------

def test_full_flow_ui_create_product(app, auth_client):
    """UI product creation creates audit entry with correct user_id."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("DELETE FROM audit_log WHERE action IN ('product_created', 'api.product.create')")
            # Create a supplier for the test
            cur.execute(
                "INSERT INTO suppliers (name, initials, location, lead_days) VALUES ('Test Supplier', 'TS', 'Test', 3) RETURNING id"
            )
            supplier_id = cur.fetchone()["id"]

    sku = f"AT-UI-{RUN}-{uuid.uuid4().hex[:6].upper()}"
    form_data = {
        "sku": sku,
        "name": "UI Audit Test",
        "category": "Test",
        "warehouse": "WH-Test",
        "current_stock": "5",
        "reorder_point": "5",
        "unit_price": "10.0",
        "supplier_id": str(supplier_id),
    }

    # Create via UI form
    resp = auth_client.post("/products/new", data=form_data, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        with get_cursor() as cur:
            # Find the created product
            cur.execute("SELECT id FROM products WHERE sku = %s", (sku,))
            row = cur.fetchone()
            assert row, "Product not created via UI"
            product_id = row["id"]

            # Verify audit entry exists with correct user_id
            cur.execute(
                """
                SELECT user_id, action FROM audit_log
                WHERE target_type = 'product' AND target_id = %s
                ORDER BY created_at DESC LIMIT 1
                """,
                (product_id,),
            )
            audit = cur.fetchone()
            assert audit is not None, "No audit entry for UI product creation"
            assert audit["user_id"] is not None, "Audit entry should have user_id"
            assert audit["action"] in ("product_created", "api.product.create")

    # Cleanup
    with app.app_context():
        _cleanup_product(product_id)


# ---------------------------------------------------------------------------
# 9. Concurrent users isolation
# ---------------------------------------------------------------------------

def test_concurrent_users_isolation(app):
    """Concurrent transactions from different users don't leak user_id."""
    results = {"user1": [], "user2": []}
    errors = []

    def worker(user_label: str, user_id: int):
        try:
            with app.app_context():
                with get_cursor(commit=True) as cur:
                    # Set GUC for this transaction
                    cur.execute("SET LOCAL app.current_user_id = %s", (user_id,))

                    # Create a product (fires trigger)
                    sku = f"AT-CONC-{RUN}-{user_label}-{uuid.uuid4().hex[:6].upper()}"
                    cur.execute(
                        """
                        INSERT INTO products (sku, name, category, warehouse, current_stock,
                                              reorder_point, unit_price)
                        VALUES (%s, %s, 'Concurrent', 'WH-Test', 0, 5, 10.0)
                        RETURNING id
                        """,
                        (sku, f"Concurrent {user_label}"),
                    )
                    product_id = cur.fetchone()["id"]

                    # Verify audit_log captured the correct user_id
                    cur.execute(
                        """
                        SELECT user_id FROM audit_log
                        WHERE target_type = 'product' AND target_id = %s
                        ORDER BY created_at DESC LIMIT 1
                        """,
                        (product_id,),
                    )
                    audit = cur.fetchone()
                    results[user_label].append(audit["user_id"] if audit else None)

                    # Cleanup
                    cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{user_label}: {exc}")

    # Run two threads with different user_ids
    t1 = threading.Thread(target=worker, args=("user1", 100))
    t2 = threading.Thread(target=worker, args=("user2", 200))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert not errors, f"Thread errors: {errors}"
    assert results["user1"] == [100], f"User1 audit leaked: {results['user1']}"
    assert results["user2"] == [200], f"User2 audit leaked: {results['user2']}"


# ---------------------------------------------------------------------------
# 10. Unauthenticated request audit NULL user
# ---------------------------------------------------------------------------

def test_unauthenticated_request_audit_null_user(app, client):
    """Unauthenticated requests should have NULL user_id in audit (if any)."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("DELETE FROM audit_log WHERE action = 'unauth_test'")

    # Direct database insert without setting GUC (simulates unauthenticated)
    with app.app_context():
        with get_cursor(commit=True) as cur:
            # Insert directly without setting app.current_user_id
            cur.execute(
                """
                INSERT INTO products (sku, name, category, warehouse, current_stock,
                                      reorder_point, unit_price)
                VALUES (%s, %s, 'UnauthTest', 'WH-Test', 0, 5, 10.0)
                RETURNING id
                """,
                (f"AT-UNAUTH-{RUN}-{uuid.uuid4().hex[:6].upper()}", "Unauth Product"),
            )
            product_id = cur.fetchone()["id"]

            # Check audit_log - user_id should be NULL since no GUC was set
            cur.execute(
                """
                SELECT user_id FROM audit_log
                WHERE target_type = 'product' AND target_id = %s
                ORDER BY created_at DESC LIMIT 1
                """,
                (product_id,),
            )
            audit = cur.fetchone()
            assert audit is not None, "Trigger should fire even without GUC"
            assert audit["user_id"] is None, (
                f"Unauthenticated operation should have NULL user_id, got {audit['user_id']}"
            )

            # Cleanup
            cur.execute("DELETE FROM products WHERE id = %s", (product_id,))


# ---------------------------------------------------------------------------
# Additional: AuditRepository.record uses current_app_user_id when user_id=None
# ---------------------------------------------------------------------------

def test_audit_repository_uses_guc_when_user_id_none(app, admin_user_id):
    """AuditRepository.record should use current_app_user_id() when user_id=None."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            # Set GUC (use set_config for custom GUC)
            cur.execute("SELECT set_config('app.current_user_id', %s, true)", (str(admin_user_id),))

            # Call AuditRepository.record with user_id=None, passing the cursor
            AuditRepository.record(
                user_id=None,
                action="test_guc_fallback",
                target_type="test",
                target_id=1,
                detail={"test": True},
                cur=cur,
            )

            # Verify audit_log has the GUC user_id
            cur.execute(
                """
                SELECT user_id FROM audit_log
                WHERE action = 'test_guc_fallback'
                ORDER BY created_at DESC LIMIT 1
                """
            )
            audit = cur.fetchone()
            assert audit is not None, "Audit entry not created"
            assert audit["user_id"] == admin_user_id, (
                f"AuditRepository should use GUC when user_id=None, got {audit['user_id']}"
            )

            # Cleanup
            cur.execute("DELETE FROM audit_log WHERE action = 'test_guc_fallback'")


# ---------------------------------------------------------------------------
# Additional: sp_audit_record uses current_app_user_id default
# ---------------------------------------------------------------------------

def test_sp_audit_record_uses_guc_default(app):
    """sp_audit_record should use current_app_user_id() as default for p_user_id."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            # Set GUC (use set_config for custom GUC)
            cur.execute("SELECT set_config('app.current_user_id', %s, true)", (str(888),))

            # Call sp_audit_record without explicit user_id (NULL)
            cur.execute(
                "SELECT sp_audit_record(NULL, %s, %s, %s, %s, %s)",
                ("test_sp_default", "test", 1, '{"test": true}', None),
            )

            # Verify audit_log has the GUC user_id
            cur.execute(
                """
                SELECT user_id FROM audit_log
                WHERE action = 'test_sp_default'
                ORDER BY created_at DESC LIMIT 1
                """
            )
            audit = cur.fetchone()
            assert audit is not None, "Audit entry not created"
            assert audit["user_id"] == 888, (
                f"sp_audit_record should use GUC default, got {audit['user_id']}"
            )

            # Cleanup
            cur.execute("DELETE FROM audit_log WHERE action = 'test_sp_default'")