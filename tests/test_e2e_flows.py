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
                cur.execute("DELETE FROM movements WHERE product_id = %s", (pid,))
                cur.execute("DELETE FROM purchase_orders WHERE product_id = %s", (pid,))
            cur.execute("DELETE FROM products WHERE sku LIKE %s", (f"%{RUN}%",))
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
