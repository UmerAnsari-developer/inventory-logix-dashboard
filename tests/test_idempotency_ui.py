"""GAP-018: UI form idempotency — form-key fallback, redirect record/replay.

Covers the extended @idempotent() decorator on ui.py routes:
- key resolution falls back to the hidden ``idempotency_key`` form field
- 302 responses are recorded as {"redirect": Location} and replayed without
  re-executing the view (no second row)
- 200 HTML re-renders (validation errors) are NOT recorded — the reservation
  is released so the user can fix input and retry
- missing key passes through (required=False default)
"""
from __future__ import annotations

import uuid

import pytest

from app.database import get_cursor

RUN = uuid.uuid4().hex[:8].upper()


@pytest.fixture(autouse=True)
def _cleanup(app):
    """Remove rows created by these tests (uuid-suffixed, shared dev DB safe)."""
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
                        (f"ui-test-{RUN}%",))


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


def _mk_product(app, *, stock: int = 0) -> int:
    with app.app_context():
        with get_cursor(commit=True) as cur:
            sku = f"UI-{RUN}-{uuid.uuid4().hex[:6].upper()}"
            cur.execute(
                """
                INSERT INTO products (sku, name, category, warehouse, current_stock,
                                      reorder_point, unit_price)
                VALUES (%s, 'UI idempotency test', 'Test', 'WH-Test', %s, 5, 10.0)
                RETURNING id
                """,
                (sku, stock),
            )
            return cur.fetchone()["id"]


def _movement_count(app, product_id: int) -> int:
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM movements WHERE product_id = %s",
                        (product_id,))
            return int(cur.fetchone()["c"])


# ── unit: key resolution ─────────────────────────────────────────────────────

def test_form_key_fallback_extracted(app):
    """No headers → the hidden form field supplies the key."""
    from app.utils.idempotency import _get_idempotency_key

    with app.test_request_context("/movements/new", method="POST",
                                  data={"idempotency_key": f"ui-test-{RUN}-form"}):
        assert _get_idempotency_key() == f"ui-test-{RUN}-form"


def test_header_key_wins_over_form(app):
    with app.test_request_context(
        "/movements/new", method="POST",
        data={"idempotency_key": f"ui-test-{RUN}-form"},
        headers={"Idempotency-Key": f"ui-test-{RUN}-header"},
    ):
        from app.utils.idempotency import _get_idempotency_key

        assert _get_idempotency_key() == f"ui-test-{RUN}-header"


# ── pass-through ─────────────────────────────────────────────────────────────

def test_missing_key_passes_through(app):
    """POST without any key → executes normally, no replay marker."""
    pid = _mk_product(app, stock=10)
    client = _session_client(app, "admin")
    resp = client.post("/movements/new", data={
        "product_id": pid, "type": "IN", "quantity": "3",
    })
    assert resp.status_code == 302
    assert "Idempotency-Replayed" not in resp.headers
    assert _movement_count(app, pid) == 1


# ── double-submit: one row, replayed redirect ────────────────────────────────

def test_double_submit_movement_creates_one_row(app):
    pid = _mk_product(app, stock=100)
    key = f"ui-test-{RUN}-mv"
    client = _session_client(app, "admin")
    data = {"product_id": pid, "type": "IN", "quantity": "5", "idempotency_key": key}

    first = client.post("/movements/new", data=data)
    assert first.status_code == 302
    assert "Idempotency-Replayed" not in first.headers
    assert _movement_count(app, pid) == 1

    second = client.post("/movements/new", data=data)
    assert second.status_code == 302
    assert second.headers["Idempotency-Replayed"] == "true"
    assert second.headers["Location"] == first.headers["Location"]
    assert _movement_count(app, pid) == 1  # replay did NOT execute the view


def test_double_submit_product_create(app):
    sku = f"UI-{RUN}-{uuid.uuid4().hex[:6].upper()}"
    key = f"ui-test-{RUN}-prod"
    client = _session_client(app, "admin")
    data = {"sku": sku, "name": "Double submit product", "warehouse": "WH-Test",
            "unit_price": "10", "idempotency_key": key}

    first = client.post("/products/new", data=data)
    assert first.status_code == 302

    second = client.post("/products/new", data=data)
    assert second.status_code == 302
    assert second.headers["Idempotency-Replayed"] == "true"
    assert second.headers["Location"] == first.headers["Location"]

    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM products WHERE sku = %s", (sku,))
            assert int(cur.fetchone()["c"]) == 1


def test_double_submit_po_create(app):
    pid = _mk_product(app, stock=0)
    key = f"ui-test-{RUN}-po"
    po_number = f"PO-UI-{RUN}-{uuid.uuid4().hex[:6].upper()}"
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT id FROM suppliers ORDER BY id LIMIT 1")
            row = cur.fetchone()
            assert row, "no suppliers seeded"
    client = _session_client(app, "admin")
    data = {"po_number": po_number, "supplier_id": row["id"], "product_id": pid,
            "quantity": "4", "unit_cost": "2.5", "status": "draft",
            "idempotency_key": key}

    first = client.post("/purchase-orders", data=data)
    assert first.status_code == 302

    second = client.post("/purchase-orders", data=data)
    assert second.status_code == 302
    assert second.headers["Idempotency-Replayed"] == "true"
    assert second.headers["Location"] == first.headers["Location"]

    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM purchase_orders WHERE po_number = %s",
                        (po_number,))
            assert int(cur.fetchone()["c"]) == 1


def test_double_submit_po_status(app):
    pid = _mk_product(app, stock=0)
    po_number = f"PO-UI-{RUN}-{uuid.uuid4().hex[:6].upper()}"
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT id FROM suppliers ORDER BY id LIMIT 1")
            supplier_id = cur.fetchone()["id"]
            cur.execute(
                """
                INSERT INTO purchase_orders (po_number, supplier_id, product_id,
                                             quantity, unit_cost, status)
                VALUES (%s, %s, %s, 2, 1.0, 'draft') RETURNING id
                """,
                (po_number, supplier_id, pid),
            )
            po_id = cur.fetchone()["id"]

    key = f"ui-test-{RUN}-postatus"
    client = _session_client(app, "admin")
    data = {"status": "approved", "idempotency_key": key}

    first = client.post(f"/purchase-orders/{po_id}/status", data=data)
    assert first.status_code == 302

    second = client.post(f"/purchase-orders/{po_id}/status", data=data)
    assert second.status_code == 302
    assert second.headers["Idempotency-Replayed"] == "true"
    assert second.headers["Location"] == first.headers["Location"]

    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT status FROM purchase_orders WHERE id = %s", (po_id,))
            assert cur.fetchone()["status"] == "approved"


# ── validation errors are retryable ─────────────────────────────────────────

def test_validation_error_not_cached(app):
    """200 HTML re-render (insufficient stock) → not recorded, retry executes."""
    pid = _mk_product(app, stock=2)
    key = f"ui-test-{RUN}-verr"
    client = _session_client(app, "admin")
    data = {"product_id": pid, "type": "OUT", "quantity": "50", "idempotency_key": key}

    first = client.post("/movements/new", data=data)
    assert first.status_code == 200  # re-render with flash error
    assert "Idempotency-Replayed" not in first.headers

    second = client.post("/movements/new", data=data)
    # Retry re-executes (not 409, not a replay) — the key was released.
    assert second.status_code == 200
    assert "Idempotency-Replayed" not in second.headers

    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM idempotency_keys WHERE key = %s",
                        (key,))
            assert int(cur.fetchone()["c"]) == 0  # reservation released
