"""GAP-015: end-to-end critical flows via the Flask test client.

No browsers (disk constraint) — the test client exercises the full stack:
routing → decorators → views → services → stored procedures → PostgreSQL.

Flows: full procurement cycle (with one explicit UI idempotency key), viewer
RBAC negatives, viewer read-only, invalid movement rejection, login/logout.
Teardown deletes only rows these tests created (uuid-suffixed SKUs).
"""
from __future__ import annotations

import uuid

import pytest

from app.database import get_cursor

RUN = uuid.uuid4().hex[:8].upper()


@pytest.fixture(autouse=True)
def _cleanup(app):
    yield
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT id FROM products WHERE sku LIKE %s", (f"%{RUN}%",))
            ids = [r["id"] for r in cur.fetchall()]
            for pid in ids:
                cur.execute(
                    "DELETE FROM goods_receipts WHERE po_id IN "
                    "(SELECT id FROM purchase_orders WHERE product_id = %s)",
                    (pid,),
                )
                cur.execute("DELETE FROM movements WHERE product_id = %s", (pid,))
                cur.execute("DELETE FROM purchase_orders WHERE product_id = %s", (pid,))
            cur.execute("DELETE FROM products WHERE sku LIKE %s", (f"%{RUN}%",))
            cur.execute(
                "DELETE FROM goods_receipts WHERE po_id IN "
                "(SELECT id FROM purchase_orders WHERE po_number LIKE %s)",
                (f"%{RUN}%",),
            )
            cur.execute("DELETE FROM purchase_orders WHERE po_number LIKE %s",
                        (f"%{RUN}%",))
            cur.execute("DELETE FROM idempotency_keys WHERE key LIKE %s",
                        (f"e2e-{RUN}%",))


def _session_client(app, username: str):
    """Authenticated client without hitting the /auth/login rate limiter.

    Mirrors tests/test_batch3_phase2.py: uid fetched in its own app context;
    client created and used OUTSIDE any ambient app context.
    """
    from flask_login.utils import _create_identifier

    from app.repositories import UserRepository

    with app.app_context():
        user = UserRepository.find_by_username(username)
        assert user is not None, f"missing user {username}"
        uid = user.id

    c = app.test_client()
    ident_box: dict = {}

    def _capture():
        ident_box["id"] = _create_identifier()

    app.before_request_funcs.setdefault(None, []).append(_capture)
    try:
        resp = c.get("/static/img/favicon.svg")
        assert resp.status_code == 200
    finally:
        app.before_request_funcs[None].remove(_capture)

    with c.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
        sess["_id"] = ident_box["id"]
    return c


def _db_stock(app, product_id: int) -> int:
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT current_stock FROM products WHERE id = %s",
                        (product_id,))
            return int(cur.fetchone()["current_stock"])


def _db_po_status(app, po_id: int) -> str:
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT status FROM purchase_orders WHERE id = %s", (po_id,))
            return cur.fetchone()["status"]


# ── Flow 1: full procurement cycle ───────────────────────────────────────────

def test_full_procurement_cycle(app):
    client = _session_client(app, "admin")

    # Browse
    assert client.get("/").status_code == 200
    assert client.get("/inventory").status_code == 200

    # Create product (uuid SKU)
    sku = f"E2E-{RUN}-{uuid.uuid4().hex[:6].upper()}"
    resp = client.post("/products/new", data={
        "sku": sku, "name": "E2E procurement product", "warehouse": "WH-Test",
        "unit_price": "10", "reorder_point": "5", "current_stock": "0",
    })
    assert resp.status_code == 302
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT id FROM products WHERE sku = %s", (sku,))
            product_id = cur.fetchone()["id"]

    # Record movement IN — explicit idempotency_key covers the UI path E2E
    resp = client.post("/movements/new", data={
        "product_id": product_id, "type": "IN", "quantity": "50",
        "reference": "e2e-initial", "idempotency_key": f"e2e-{RUN}-mv",
    })
    assert resp.status_code == 302
    assert _db_stock(app, product_id) == 50

    # Reorder alerts page renders
    assert client.get("/reorder-alerts").status_code == 200

    # Create PO
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT id FROM suppliers ORDER BY id LIMIT 1")
            supplier_id = cur.fetchone()["id"]
    po_number = f"PO-E2E-{RUN}-{uuid.uuid4().hex[:6].upper()}"
    resp = client.post("/purchase-orders", data={
        "po_number": po_number, "supplier_id": supplier_id,
        "product_id": product_id, "quantity": "10", "unit_cost": "5",
        "status": "draft",
    })
    assert resp.status_code == 302
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT id FROM purchase_orders WHERE po_number = %s",
                        (po_number,))
            po_id = cur.fetchone()["id"]

    # Transition ×3: approved → in_transit → received
    for status in ("approved", "in_transit", "received"):
        resp = client.post(f"/purchase-orders/{po_id}/status", data={"status": status})
        assert resp.status_code == 302
    assert _db_po_status(app, po_id) == "received"

    # sp_po_transition('received') inserted an IN movement + stock delta
    with app.app_context():
        with get_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM movements WHERE product_id = %s",
                (product_id,),
            )
            assert int(cur.fetchone()["c"]) == 2  # IN 50 + PO-received IN 10

    # Final stock via API (fresh product:<id> key — never cached in this flow)
    resp = client.get(f"/api/products/{product_id}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert int(body["data"]["current_stock"]) == 60
    assert _db_stock(app, product_id) == 60


# ── Flow 2: viewer writes are forbidden ──────────────────────────────────────

def test_viewer_write_forbidden(app):
    client = _session_client(app, "viewer")
    assert client.post("/products/new", data={
        "sku": f"E2E-{RUN}-X", "name": "nope", "warehouse": "WH-Test",
        "unit_price": "1",
    }).status_code == 403
    assert client.post("/movements/new", data={
        "product_id": 1, "type": "IN", "quantity": "1",
    }).status_code == 403
    assert client.post("/purchase-orders", data={
        "supplier_id": 1, "product_id": 1, "quantity": "1", "unit_cost": "1",
    }).status_code == 403


# ── Flow 3: viewer read-only is fine ─────────────────────────────────────────

def test_viewer_read_only_ok(app):
    client = _session_client(app, "viewer")
    assert client.get("/").status_code == 200
    assert client.get("/inventory").status_code == 200
    assert client.get("/reports").status_code == 200


# ── Flow 4: invalid movement rejected, stock unchanged ───────────────────────

def test_invalid_movement_rejected(app):
    client = _session_client(app, "admin")
    sku = f"E2E-{RUN}-{uuid.uuid4().hex[:6].upper()}"
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO products (sku, name, category, warehouse, current_stock,
                                      reorder_point, unit_price)
                VALUES (%s, 'E2E stock guard', 'Test', 'WH-Test', 5, 0, 1.0)
                RETURNING id
                """,
                (sku,),
            )
            product_id = cur.fetchone()["id"]

    resp = client.post("/movements/new", data={
        "product_id": product_id, "type": "OUT", "quantity": "10",
    })
    assert resp.status_code == 200  # re-render with flash error, no redirect
    assert _db_stock(app, product_id) == 5  # trigger-enforced: unchanged
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM movements WHERE product_id = %s",
                        (product_id,))
            assert int(cur.fetchone()["c"]) == 0


# ── Flow 5: login / logout cycle ─────────────────────────────────────────────

def test_login_logout_cycle(app):
    client = app.test_client()

    # Bad password → 401 re-render with error
    resp = client.post("/auth/login", data={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401

    # Good credentials → redirect to dashboard
    resp = client.post("/auth/login", data={"username": "admin", "password": "Admin@123"})
    assert resp.status_code == 302
    resp = client.get("/", follow_redirects=True)
    assert resp.status_code == 200

    # Logout → session ends; protected page bounces to login
    resp = client.post("/auth/logout")
    assert resp.status_code == 302
    resp = client.get("/inventory", follow_redirects=False)
    assert resp.status_code == 302  # login_required bounce


# ============================================================
# BATCH 1: GOODS RECEIVING INTEGRITY TESTS
# ============================================================

import uuid


def _mk_po_in_transit(app, quantity=10):
    """Create product, supplier, and PO in in_transit status. Returns (product_id, po_id)."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            # Create product
            sku = f"RECV-{RUN}-{uuid.uuid4().hex[:6].upper()}"
            cur.execute("""
                INSERT INTO products (sku, name, category, warehouse, current_stock,
                                      reorder_point, unit_price)
                VALUES (%s, 'Receive Test Product', 'Test', 'WH-Test', 50, 5, 10.0)
                RETURNING id
            """, (sku,))
            product_id = cur.fetchone()["id"]
            
            # Get/create supplier
            cur.execute("SELECT id FROM suppliers ORDER BY id LIMIT 1")
            row = cur.fetchone()
            if row:
                supplier_id = row["id"]
            else:
                cur.execute("""
                    INSERT INTO suppliers (name, initials, location, lead_days)
                    VALUES ('Receive Test Supplier', 'RTS', 'Test City', 3)
                    RETURNING id
                """)
                supplier_id = cur.fetchone()["id"]
            
            # Create PO
            po_number = f"PO-RECV-{RUN}-{uuid.uuid4().hex[:6].upper()}"
            cur.execute("""
                INSERT INTO purchase_orders (po_number, supplier_id, product_id, quantity, unit_cost, status)
                VALUES (%s, %s, %s, %s, 5.0, 'draft')
                RETURNING id
            """, (po_number, supplier_id, product_id, quantity))
            po_id = cur.fetchone()["id"]
            
            # Transition: draft -> approved -> in_transit
            cur.execute("SELECT sp_po_transition(%s, %s)", (po_id, 'approved'))
            cur.execute("SELECT sp_po_transition(%s, %s)", (po_id, 'in_transit'))
    
    return product_id, po_id


def _session_client_admin(app):
    """Admin session client for receiving tests."""
    return _session_client(app, "admin")


# ── Test 13: Partial receipt 8 of 10 stays in_transit ──────────────────────────
def test_partial_receipt_8_of_10_stays_in_transit(app):
    """Receive 8 of 10 → PO stays in_transit, received_quantity=8, on_order-=8, stock+=8."""
    client = _session_client_admin(app)
    product_id, po_id = _mk_po_in_transit(app, quantity=10)
    
    # Initial state
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT current_stock, on_order FROM products WHERE id = %s", (product_id,))
            initial = cur.fetchone()
            cur.execute("SELECT received_quantity, status FROM purchase_orders WHERE id = %s", (po_id,))
            po_initial = cur.fetchone()
    
    # Receive 8
    import uuid
    resp = client.post(f"/purchase-orders/{po_id}/receive", data={
        "quantity": "8",
        "notes": "Partial delivery",
        "location": "WH1",
        "idempotency_key": f"idem-{uuid.uuid4().hex[:12]}"
    })
    assert resp.status_code in (200, 302)  # success redirect or form re-render
    
    # Verify PO state
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT received_quantity, status FROM purchase_orders WHERE id = %s", (po_id,))
            po = cur.fetchone()
            assert po["received_quantity"] == 8
            assert po["status"] == "in_transit"
            
            cur.execute("SELECT current_stock, on_order FROM products WHERE id = %s", (product_id,))
            prod = cur.fetchone()
            assert prod["current_stock"] == 58  # 50 + 8
            assert prod["on_order"] == 2        # 10 - 8
            
            # Goods receipt row created
            cur.execute("SELECT quantity, received_by, notes, location FROM goods_receipts WHERE po_id = %s", (po_id,))
            gr = cur.fetchone()
            assert gr is not None
            assert gr["quantity"] == 8
            assert gr["notes"] == "Partial delivery"
            assert gr["location"] == "WH1"
            
            # Movement created with received quantity
            cur.execute("SELECT quantity, user_id FROM movements WHERE product_id = %s ORDER BY id DESC LIMIT 1", (product_id,))
            mv = cur.fetchone()
            assert mv["quantity"] == 8
            assert mv["user_id"] is not None


# ── Test 14: Partial receipt second receipt completes PO ───────────────────────
def test_partial_receipt_second_receipt_completes_po(app):
    """After partial 8, receive remaining 2 → PO moves to received, received_quantity=10, on_order=0."""
    client = _session_client_admin(app)
    product_id, po_id = _mk_po_in_transit(app, quantity=10)
    
    # First receipt: 8
    import uuid
    client.post(f"/purchase-orders/{po_id}/receive", data={
        "quantity": "8",
        "notes": "Partial",
        "location": "WH1",
        "idempotency_key": f"idem-{uuid.uuid4().hex[:12]}"
    })
    
    # Second receipt: remaining 2
    resp = client.post(f"/purchase-orders/{po_id}/receive", data={
        "quantity": "2",
        "notes": "Final",
        "location": "WH1",
        "idempotency_key": f"idem-{uuid.uuid4().hex[:12]}"
    })
    assert resp.status_code in (200, 302)
    
    # Verify PO completed
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT received_quantity, status FROM purchase_orders WHERE id = %s", (po_id,))
            po = cur.fetchone()
            assert po["received_quantity"] == 10
            assert po["status"] == "received"
            
            cur.execute("SELECT on_order FROM products WHERE id = %s", (product_id,))
            prod = cur.fetchone()
            assert prod["on_order"] == 0
            
            # Two goods receipts
            cur.execute("SELECT COUNT(*) AS c, SUM(quantity) AS total FROM goods_receipts WHERE po_id = %s", (po_id,))
            gr = cur.fetchone()
            assert gr["c"] == 2
            assert gr["total"] == 10


# ── Test 15: on_order decrements by received qty ───────────────────────────────
def test_partial_receipt_on_order_decrements_by_received(app):
    """Receive 5 of 20 → on_order decreases by 5 (not 20)."""
    client = _session_client_admin(app)
    product_id, po_id = _mk_po_in_transit(app, quantity=20)
    
    import uuid
    client.post(f"/purchase-orders/{po_id}/receive", data={
        "quantity": "5",
        "idempotency_key": f"idem-{uuid.uuid4().hex[:12]}"
    })
    
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT on_order FROM products WHERE id = %s", (product_id,))
            assert cur.fetchone()["on_order"] == 15  # 20 - 5


# ── Test 16: stock increments by received qty ──────────────────────────────────
def test_partial_receipt_stock_increments_by_received(app):
    """Receive 8 of 10 → current_stock increases by 8 (not 10)."""
    client = _session_client_admin(app)
    product_id, po_id = _mk_po_in_transit(app, quantity=10)
    
    import uuid
    client.post(f"/purchase-orders/{po_id}/receive", data={
        "quantity": "8",
        "idempotency_key": f"idem-{uuid.uuid4().hex[:12]}"
    })
    
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
            assert cur.fetchone()["current_stock"] == 58  # 50 + 8


# ── Test 17: goods_receipt row created ─────────────────────────────────────────
def test_partial_receipt_goods_receipt_row_created(app):
    """Receive creates goods_receipts row with all fields."""
    client = _session_client_admin(app)
    product_id, po_id = _mk_po_in_transit(app, quantity=10)
    
    import uuid
    client.post(f"/purchase-orders/{po_id}/receive", data={
        "quantity": "8",
        "notes": "Test receipt",
        "location": "WH1",
        "idempotency_key": f"idem-{uuid.uuid4().hex[:12]}"
    })
    
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("""
                SELECT quantity, received_by, notes, location, idempotency_key
                FROM goods_receipts WHERE po_id = %s
            """, (po_id,))
            gr = cur.fetchone()
            assert gr is not None
            assert gr["quantity"] == 8
            assert gr["notes"] == "Test receipt"
            assert gr["location"] == "WH1"
            assert gr["idempotency_key"] is not None


# ── Test 18: movement created with received qty ────────────────────────────────
def test_partial_receipt_movement_created_with_qty(app):
    """Movement quantity matches received quantity; user_id recorded."""
    client = _session_client_admin(app)
    product_id, po_id = _mk_po_in_transit(app, quantity=10)
    
    import uuid
    client.post(f"/purchase-orders/{po_id}/receive", data={
        "quantity": "8",
        "idempotency_key": f"idem-{uuid.uuid4().hex[:12]}"
    })
    
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("""
                SELECT quantity, user_id FROM movements
                WHERE product_id = %s ORDER BY id DESC LIMIT 1
            """, (product_id,))
            mv = cur.fetchone()
            assert mv["quantity"] == 8
            assert mv["user_id"] is not None


# ── Test 19: Full receipt backward compat (no qty param) ───────────────────────
def test_full_receipt_backward_compat_no_qty_param(app):
    """Receive without quantity param → defaults to full PO quantity."""
    client = _session_client_admin(app)
    product_id, po_id = _mk_po_in_transit(app, quantity=10)
    
    import uuid
    resp = client.post(f"/purchase-orders/{po_id}/receive", data={
        "notes": "Full delivery",
        "location": "WH1",
        "idempotency_key": f"idem-{uuid.uuid4().hex[:12]}"
    })
    assert resp.status_code in (200, 302)
    
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT received_quantity, status FROM purchase_orders WHERE id = %s", (po_id,))
            po = cur.fetchone()
            assert po["received_quantity"] == 10
            assert po["status"] == "received"
            
            cur.execute("SELECT on_order FROM products WHERE id = %s", (product_id,))
            assert cur.fetchone()["on_order"] == 0
            
            cur.execute("SELECT quantity FROM movements WHERE product_id = %s ORDER BY id DESC LIMIT 1", (product_id,))
            assert cur.fetchone()["quantity"] == 10


# ── Test 20: Full receipt received_quantity defaults to quantity ───────────────
def test_full_receipt_received_quantity_defaults_to_quantity(app):
    """Full receipt sets received_quantity = quantity."""
    client = _session_client_admin(app)
    product_id, po_id = _mk_po_in_transit(app, quantity=15)
    
    import uuid
    client.post(f"/purchase-orders/{po_id}/receive", data={
        "idempotency_key": f"idem-{uuid.uuid4().hex[:12]}"
    })
    
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT received_quantity FROM purchase_orders WHERE id = %s", (po_id,))
            assert cur.fetchone()["received_quantity"] == 15


# ── Test 21: Double receipt same idempotency key → one row ─────────────────────
def test_double_receipt_same_idempotency_key_one_row(app):
    """Two requests with same idempotency key → one goods_receipt row."""
    client = _session_client_admin(app)
    product_id, po_id = _mk_po_in_transit(app, quantity=10)
    
    import uuid
    same_key = f"idem-{uuid.uuid4().hex[:12]}"
    
    # Request 1
    client.post(f"/purchase-orders/{po_id}/receive", data={
        "quantity": "5",
        "idempotency_key": same_key
    })
    # Request 2 (same key)
    resp = client.post(f"/purchase-orders/{po_id}/receive", data={
        "quantity": "5",
        "idempotency_key": same_key
    })
    assert resp.status_code in (200, 302)
    
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c, SUM(quantity) AS total FROM goods_receipts WHERE po_id = %s", (po_id,))
            gr = cur.fetchone()
            assert gr["c"] == 1
            assert gr["total"] == 5


# ── Test 22: Double receipt same idempotency key → one movement ────────────────
def test_double_receipt_same_idempotency_key_one_movement(app):
    """Two requests with same idempotency key → one movement row."""
    client = _session_client_admin(app)
    product_id, po_id = _mk_po_in_transit(app, quantity=10)
    
    import uuid
    same_key = f"idem-{uuid.uuid4().hex[:12]}"
    
    client.post(f"/purchase-orders/{po_id}/receive", data={
        "quantity": "5",
        "idempotency_key": same_key
    })
    client.post(f"/purchase-orders/{po_id}/receive", data={
        "quantity": "5",
        "idempotency_key": same_key
    })
    
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) AS c FROM movements
                WHERE product_id = %s AND reference LIKE %s
            """, (product_id, f"%PO-RECV-{RUN}%"))
            assert cur.fetchone()["c"] == 1


# ── Test 23: Double receipt different keys → both succeed ──────────────────────
def test_double_receipt_different_keys_both_succeed(app):
    """Two receives with different keys on same PO → both succeed."""
    client = _session_client_admin(app)
    product_id, po_id = _mk_po_in_transit(app, quantity=10)
    
    import uuid
    client.post(f"/purchase-orders/{po_id}/receive", data={
        "quantity": "5",
        "idempotency_key": f"idem-{uuid.uuid4().hex[:12]}"
    })
    client.post(f"/purchase-orders/{po_id}/receive", data={
        "quantity": "3",
        "idempotency_key": f"idem-{uuid.uuid4().hex[:12]}"
    })
    
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT received_quantity, status FROM purchase_orders WHERE id = %s", (po_id,))
            po = cur.fetchone()
            assert po["received_quantity"] == 8
            assert po["status"] == "in_transit"
            
            cur.execute("SELECT COUNT(*) AS c FROM goods_receipts WHERE po_id = %s", (po_id,))
            assert cur.fetchone()["c"] == 2


# ── Test 24: Cancelled PO cannot receive ───────────────────────────────────────
def test_cancelled_po_cannot_receive(app):
    """Cancelled PO → receive rejected, no goods_receipt, no movement."""
    client = _session_client_admin(app)
    product_id, po_id = _mk_po_in_transit(app, quantity=10)
    
    # Cancel the PO
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_po_transition(%s, %s)", (po_id, 'cancelled'))
    
    import uuid
    resp = client.post(f"/purchase-orders/{po_id}/receive", data={
        "quantity": "5",
        "idempotency_key": f"idem-{uuid.uuid4().hex[:12]}"
    })
    # Should fail with error (flash message in session, but we check DB state)
    
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT status FROM purchase_orders WHERE id = %s", (po_id,))
            assert cur.fetchone()["status"] == "cancelled"
            
            cur.execute("SELECT COUNT(*) AS c FROM goods_receipts WHERE po_id = %s", (po_id,))
            assert cur.fetchone()["c"] == 0
            
            cur.execute("SELECT COUNT(*) AS c FROM movements WHERE product_id = %s", (product_id,))
            assert cur.fetchone()["c"] == 0  # no new movement


# ── Test 25: Multiple partial receipts sum correctly ───────────────────────────
def test_multiple_partial_receipts_sum_correctly(app):
    """30 + 40 + 30 = 100 → PO received, sums match."""
    client = _session_client_admin(app)
    product_id, po_id = _mk_po_in_transit(app, quantity=100)
    
    import uuid
    for qty, key_suffix in [(30, "1"), (40, "2"), (30, "3")]:
        client.post(f"/purchase-orders/{po_id}/receive", data={
            "quantity": str(qty),
            "idempotency_key": f"idem-{uuid.uuid4().hex[:12]}-{key_suffix}"
        })
    
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT received_quantity, status FROM purchase_orders WHERE id = %s", (po_id,))
            po = cur.fetchone()
            assert po["received_quantity"] == 100
            assert po["status"] == "received"
            
            cur.execute("SELECT SUM(quantity) AS total FROM goods_receipts WHERE po_id = %s", (po_id,))
            assert cur.fetchone()["total"] == 100
            
            cur.execute("SELECT SUM(quantity) AS total FROM movements WHERE product_id = %s", (product_id,))
            # 50 initial + 100 receive = 150 total, but we only care about receive movements
            cur.execute("SELECT SUM(quantity) AS total FROM movements WHERE product_id = %s AND type = 'IN' AND reference LIKE %s", (product_id, f"%PO-RECV-{RUN}%"))
            assert cur.fetchone()["total"] == 100
            
            cur.execute("SELECT on_order FROM products WHERE id = %s", (product_id,))
            assert cur.fetchone()["on_order"] == 0


# ── Test 26: Stock integrity after three partial receipts ──────────────────────
def test_stock_integrity_after_three_partial_receipts(app):
    """Three partials totaling 100 → stock increases by 100."""
    client = _session_client_admin(app)
    product_id, po_id = _mk_po_in_transit(app, quantity=100)
    
    import uuid
    for qty in [30, 40, 30]:
        client.post(f"/purchase-orders/{po_id}/receive", data={
            "quantity": str(qty),
            "idempotency_key": f"idem-{uuid.uuid4().hex[:12]}"
        })
    
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
            assert cur.fetchone()["current_stock"] == 150  # 50 + 100


# ── Test 27: on_order decrements by received not ordered ───────────────────────
def test_on_order_decrements_by_received_not_ordered(app):
    """4 receives of 25 → on_order: 75, 50, 25, 0."""
    client = _session_client_admin(app)
    product_id, po_id = _mk_po_in_transit(app, quantity=100)
    
    import uuid
    for i, qty in enumerate([25, 25, 25, 25]):
        client.post(f"/purchase-orders/{po_id}/receive", data={
            "quantity": str(qty),
            "idempotency_key": f"idem-{uuid.uuid4().hex[:12]}-{i}"
        })
        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT on_order FROM products WHERE id = %s", (product_id,))
                expected = 100 - 25 * (i + 1)
                assert cur.fetchone()["on_order"] == expected


# ── Test 28: Goods receipt query by PO ─────────────────────────────────────────
def test_goods_receipt_query_by_po(app):
    """list_receipts(po_id=...) returns only that PO's receipts."""
    from app.repositories import PurchaseOrderRepository

    client = _session_client_admin(app)
    product_id, po_id = _mk_po_in_transit(app, quantity=10)

    import uuid
    client.post(f"/purchase-orders/{po_id}/receive", data={
        "quantity": "5",
        "idempotency_key": f"idem-{uuid.uuid4().hex[:12]}"
    })

    # Create another PO with a receipt on the same product
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT id FROM suppliers ORDER BY id LIMIT 1")
            sup_id = cur.fetchone()["id"]
            cur.execute("SELECT id FROM users ORDER BY id LIMIT 1")
            user_id = cur.fetchone()["id"]
            cur.execute("""
                INSERT INTO purchase_orders (po_number, supplier_id, product_id, quantity, unit_cost, status)
                VALUES (%s, %s, %s, 10, 5.0, 'in_transit')
                RETURNING id
            """, (f"PO-OTHER-{RUN}", sup_id, product_id))
            po2_id = cur.fetchone()["id"]

            cur.execute("""
                SELECT sp_goods_receipt_create(%s, %s, %s, %s, %s, %s)
            """, (po2_id, 3, user_id, 'Other PO receipt', 'WH2',
                  f'idem-other-{uuid.uuid4().hex[:8]}'))

    with app.app_context():
        receipts = PurchaseOrderRepository.list_receipts(po_id=po_id)
        assert len(receipts) == 1
        assert receipts[0]["po_id"] == po_id
        assert receipts[0]["quantity"] == 5


# ── Test 29: Goods receipt query by date ───────────────────────────────────────
def test_goods_receipt_query_by_date(app):
    """list_receipts(date_from, date_to) filters correctly."""
    from app.repositories import PurchaseOrderRepository
    from datetime import timedelta

    client = _session_client_admin(app)
    product_id, po_id = _mk_po_in_transit(app, quantity=10)

    import uuid
    for qty in (5, 3, 2):
        client.post(f"/purchase-orders/{po_id}/receive", data={
            "quantity": str(qty),
            "idempotency_key": f"idem-{uuid.uuid4().hex[:12]}"
        })

    # Use the receipts' own date (timezone-agnostic)
    with app.app_context():
        all_receipts = PurchaseOrderRepository.list_receipts(po_id=po_id)
        assert len(all_receipts) == 3
        receipt_date = all_receipts[0]["received_at"].date().isoformat()
        next_day = (all_receipts[0]["received_at"].date() + timedelta(days=1)).isoformat()

    with app.app_context():
        receipts = PurchaseOrderRepository.list_receipts(
            po_id=po_id, date_from=receipt_date, date_to=receipt_date
        )
        assert len(receipts) == 3

        receipts = PurchaseOrderRepository.list_receipts(
            po_id=po_id, date_from=next_day, date_to=next_day
        )
        assert receipts == []


# ── Test 30: Goods receipt query by user ───────────────────────────────────────
def test_goods_receipt_query_by_user(app):
    """list_receipts(received_by=...) returns only that user's receipts."""
    from app.repositories import PurchaseOrderRepository

    product_id, po_id = _mk_po_in_transit(app, quantity=10)

    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT id FROM users ORDER BY id LIMIT 1")
            u1 = cur.fetchone()["id"]
            cur.execute("SELECT id FROM users WHERE id <> %s ORDER BY id LIMIT 1", (u1,))
            row = cur.fetchone()
            if row is None:
                pytest.skip("needs two distinct users")
            u2 = row["id"]

            for uid, qty in ((u1, 5), (u2, 3)):
                cur.execute("""
                    SELECT sp_goods_receipt_create(%s, %s, %s, %s, %s, %s)
                """, (po_id, qty, uid, 'User receipt', 'WH1',
                      f"idem-{uuid.uuid4().hex[:12]}"))

    with app.app_context():
        receipts = PurchaseOrderRepository.list_receipts(po_id=po_id, received_by=u1)
        assert len(receipts) == 1
        assert receipts[0]["received_by"] == u1