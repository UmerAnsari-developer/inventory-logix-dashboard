"""P0 goods-receiving correctness: schema parity, single SP signature,
idempotent duplicate receipts, on_order lifecycle, receipt-history UI.

Companion to Fix/Audit_Features/Batch1/Research/p0-research.md findings A-F.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.database import get_cursor
from app.repositories import PurchaseOrderRepository
from app.services import POService, POServiceError

RUN = uuid.uuid4().hex[:8].upper()
SCHEMA_SQL = Path(__file__).parents[1] / "app" / "database" / "schema.sql"


def _mk_product(cur, stock: int = 0, on_order: int = 0) -> int:
    cur.execute(
        """
        INSERT INTO products (sku, name, category, warehouse, current_stock,
                              reorder_point, unit_price, on_order)
        VALUES (%s, 'P0 Product', 'Test', 'WH-Test', %s, 0, 10.0, %s)
        RETURNING id
        """,
        (f"P0-{RUN}-{uuid.uuid4().hex[:6].upper()}", stock, on_order),
    )
    return cur.fetchone()["id"]


def _mk_po(cur, product_id: int, *, qty: int, status: str = "draft"):
    po_number = f"PO-P0-{RUN}-{uuid.uuid4().hex[:6].upper()}"
    cur.execute("SELECT id FROM suppliers ORDER BY id LIMIT 1")
    row = cur.fetchone()
    if row:
        supplier_id = row["id"]
    else:
        cur.execute(
            "INSERT INTO suppliers (name, initials, location, lead_days) "
            "VALUES ('P0 Supplier', 'P0', 'Test', 3) RETURNING id"
        )
        supplier_id = cur.fetchone()["id"]
    cur.execute(
        """
        INSERT INTO purchase_orders (po_number, product_id, supplier_id,
                                     quantity, unit_cost, status)
        VALUES (%s, %s, %s, %s, 10.0, %s)
        RETURNING id
        """,
        (po_number, product_id, supplier_id, qty, status),
    )
    return cur.fetchone()["id"], po_number


def _product_state(app, product_id: int) -> dict:
    with app.app_context():
        with get_cursor() as cur:
            cur.execute(
                "SELECT current_stock, on_order FROM products WHERE id = %s",
                (product_id,),
            )
            return dict(cur.fetchone())


def _po_state(app, po_id: int) -> dict:
    with app.app_context():
        with get_cursor() as cur:
            cur.execute(
                "SELECT status, quantity, COALESCE(received_quantity, 0) AS received "
                "FROM purchase_orders WHERE id = %s",
                (po_id,),
            )
            return dict(cur.fetchone())


@pytest.fixture(autouse=True)
def _cleanup(app):
    yield
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "SELECT id FROM products WHERE sku LIKE %s", (f"P0-{RUN}%",)
            )
            for pid in [r["id"] for r in cur.fetchall()]:
                cur.execute(
                    "DELETE FROM goods_receipts WHERE po_id IN "
                    "(SELECT id FROM purchase_orders WHERE product_id = %s)",
                    (pid,),
                )
                cur.execute(
                    "DELETE FROM movements WHERE product_id = %s", (pid,)
                )
                cur.execute(
                    "DELETE FROM purchase_orders WHERE product_id = %s", (pid,)
                )
            cur.execute(
                "DELETE FROM idempotency_keys WHERE key LIKE %s", (f"p0-{RUN}%",)
            )
            cur.execute(
                "DELETE FROM products WHERE sku LIKE %s", (f"P0-{RUN}%",)
            )


# ── D: fresh-install schema parity ──────────────────────────────────────────

def test_schema_sql_contains_goods_receipts_ddl():
    """schema.sql must declare goods_receipts + received_quantity (fresh installs)."""
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS goods_receipts" in sql
    assert "received_quantity" in sql
    assert "idx_gr_idempotency" in sql


def test_single_sp_po_transition_signature(app):
    """Exactly one sp_po_transition exists and it is the 7-arg receive-aware form."""
    with app.app_context():
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT pg_get_function_identity_arguments(p.oid) AS args
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE p.proname = 'sp_po_transition' AND n.nspname = 'public'
                """
            )
            rows = cur.fetchall()
    assert len(rows) == 1, f"expected one signature, got {[r['args'] for r in rows]}"
    assert rows[0]["args"].startswith(
        "p_id integer, p_new_status character varying, p_received_quantity"
    )


# ── C: idempotent duplicate receipts ────────────────────────────────────────

def test_duplicate_key_applies_once(app, admin_user):
    """Same idempotency key twice: stock/received/movement/receipt applied once."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur)
            po_id, _ = _mk_po(cur, product_id, qty=10)
        PurchaseOrderRepository.transition(po_id, "approved")
        PurchaseOrderRepository.transition(po_id, "in_transit")

        key = f"p0-{RUN}-dup"
        POService.receive(po_id, 4, admin_user["id"], idempotency_key=key)
        POService.receive(po_id, 4, admin_user["id"], idempotency_key=key)

        po = _po_state(app, po_id)
        prod = _product_state(app, product_id)
        assert po["received"] == 4, po
        assert po["status"] == "in_transit", po
        assert prod["current_stock"] == 4, prod
        assert prod["on_order"] == 6, prod

        with app.app_context():
            with get_cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS c FROM goods_receipts WHERE po_id = %s",
                    (po_id,),
                )
                assert cur.fetchone()["c"] == 1
                cur.execute(
                    "SELECT COUNT(*) AS c FROM movements WHERE product_id = %s "
                    "AND type = 'IN'",
                    (product_id,),
                )
                assert cur.fetchone()["c"] == 1


def test_key_reuse_with_different_payload_rejected(app, admin_user):
    """A replayed key carrying a different quantity is a client bug, not a replay."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur)
            po_id, _ = _mk_po(cur, product_id, qty=10)
        PurchaseOrderRepository.transition(po_id, "approved")
        PurchaseOrderRepository.transition(po_id, "in_transit")

        key = f"p0-{RUN}-mismatch"
        POService.receive(po_id, 4, admin_user["id"], idempotency_key=key)
        with pytest.raises(POServiceError, match="[Ii]dempotency key"):
            POService.receive(po_id, 5, admin_user["id"], idempotency_key=key)


def test_receive_without_key_still_creates_receipt(app, admin_user):
    """Direct service calls without an HTTP key fall back to a generated one."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur)
            po_id, _ = _mk_po(cur, product_id, qty=10)
        PurchaseOrderRepository.transition(po_id, "approved")
        PurchaseOrderRepository.transition(po_id, "in_transit")

        POService.receive(po_id, 10, admin_user["id"])
        po = _po_state(app, po_id)
        assert po["received"] == 10
        assert po["status"] == "received"
        with app.app_context():
            with get_cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS c FROM goods_receipts WHERE po_id = %s",
                    (po_id,),
                )
                assert cur.fetchone()["c"] == 1


# ── B: on_order lifecycle ───────────────────────────────────────────────────

def test_cancel_after_partial_releases_only_unreceived(app, admin_user):
    """PO A (10, 4 received) + PO B (5, approved); cancel A drops on_order by 6."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur)
            po_a, _ = _mk_po(cur, product_id, qty=10)
            po_b, _ = _mk_po(cur, product_id, qty=5)
        PurchaseOrderRepository.transition(po_a, "approved")
        PurchaseOrderRepository.transition(po_a, "in_transit")
        POService.receive(po_a, 4, admin_user["id"])
        PurchaseOrderRepository.transition(po_b, "approved")
        # on_order: +10 -4 +5 = 11
        assert _product_state(app, product_id)["on_order"] == 11

        PurchaseOrderRepository.transition(po_a, "cancelled")
        # releases 10-4=6; B's 5 survives
        assert _product_state(app, product_id)["on_order"] == 5


def test_draft_cancel_is_noop_on_on_order(app):
    """Cancelling a draft PO (never counted) must not touch on_order."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur, on_order=7)
            po_id, _ = _mk_po(cur, product_id, qty=10)
        PurchaseOrderRepository.transition(po_id, "cancelled")
        assert _product_state(app, product_id)["on_order"] == 7


def test_direct_approved_create_counts_on_order(app):
    """sp_po_create with status='approved' must increment on_order."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur)
            cur.execute("SELECT id FROM suppliers ORDER BY id LIMIT 1")
            row = cur.fetchone()
            if row:
                supplier_id = row["id"]
            else:
                cur.execute(
                    "INSERT INTO suppliers (name, initials, location, lead_days) "
                    "VALUES ('P0 Supplier', 'P0', 'Test', 3) RETURNING id"
                )
                supplier_id = cur.fetchone()["id"]
            # Call sp_po_create directly to test its on_order behavior
            cur.execute(
                "SELECT sp_po_create(%s, %s, %s, %s, 10.0, 'approved', NULL)",
                (f"PO-P0-{RUN}-{uuid.uuid4().hex[:6].upper()}", supplier_id, product_id, 6)
            )
        assert _product_state(app, product_id)["on_order"] == 6
        # cleanup: POs are removed by the autouse fixture via product_id


# ── E: receipt history UI ───────────────────────────────────────────────────

def _session_client(app, username: str):
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


def test_receipt_history_renders_row(app):
    """After a receipt, GET /purchase-orders shows the row; empty state hidden."""
    from app.repositories import UserRepository
    from app.utils.cache import api_cache
    
    # Bust cache to ensure fresh data (cache is shared module-level singleton)
    api_cache.invalidate("purchase_orders:board")
    
    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur)
            po_id, po_number = _mk_po(cur, product_id, qty=10)
        PurchaseOrderRepository.transition(po_id, "approved")
        PurchaseOrderRepository.transition(po_id, "in_transit")
        
        # Use built-in admin user for receive
        admin = UserRepository.find_by_username("admin")
        POService.receive(po_id, 4, admin.id, idempotency_key=f"p0-{RUN}-ui")

        # Debug: check receipts in DB
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM goods_receipts WHERE po_id = %s", (po_id,))
            print(f"DEBUG: Receipts for PO {po_id}: {cur.fetchone()['c']}")
            cur.execute("SELECT * FROM sp_goods_receipt_list(NULL, NULL, NULL, NULL) LIMIT 5")
            rows = cur.fetchall()
            print(f"DEBUG: sp_goods_receipt_list returns {len(rows)} rows")

    # Use the built-in admin user (like test_e2e_flows.py)
    client = _session_client(app, "admin")
    html = client.get("/purchase-orders").get_data(as_text=True)
    
    # Debug: print receipt section
    idx = html.find('receipt-history-body')
    if idx > 0:
        print(f"DEBUG: receipt-history-body section: {html[idx:idx+300]}")
    else:
        print(f"DEBUG: receipt-history-body NOT FOUND in HTML")
    
    assert po_number in html
    assert 'id="receipt-history"' in html
    assert "display: none;" not in html.split('id="receipt-history"')[1][:200]
    # empty state must NOT be present when rows exist (template uses {% if not receipts %})
    assert 'id="receipt-empty"' not in html
    assert "No receipts found." not in html


def test_receipt_history_empty_state(app):
    """With no receipts, the empty-state message is visible."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT COUNT(*) AS c FROM goods_receipts")
            has_rows = cur.fetchone()["c"] > 0
    client = _session_client(app, "admin")
    html = client.get("/purchase-orders").get_data(as_text=True)
    if has_rows:
        pytest.skip("test DB already contains goods receipts from other tests")
    assert "No receipts found." in html
    assert 'id="receipt-empty" style="display: none;"' not in html
