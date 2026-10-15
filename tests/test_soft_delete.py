"""GAP-020: soft delete for movements + purchase_orders (phases 1 + 2).

Verifies the migration landed (columns, indexes, procs), that the filtered
list procs exclude soft-deleted rows, that sp_po_transition refuses deleted
POs, that soft deletes write audit rows (phase 2), and that analytics
(sp_movement_daily_totals) EXCLUDE soft-deleted rows (phase 2 reconciliation).
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


def _mk_product(app, *, stock: int = 0) -> int:
    with app.app_context():
        with get_cursor(commit=True) as cur:
            sku = f"SD-{RUN}-{uuid.uuid4().hex[:6].upper()}"
            cur.execute(
                """
                INSERT INTO products (sku, name, category, warehouse, current_stock,
                                      reorder_point, unit_price)
                VALUES (%s, 'Soft delete test', 'Test', 'WH-Test', %s, 0, 1.0)
                RETURNING id
                """,
                (sku, stock),
            )
            return cur.fetchone()["id"]


def _mk_po(app, product_id: int, *, status: str = "draft") -> int:
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT id FROM suppliers ORDER BY id LIMIT 1")
            supplier_id = cur.fetchone()["id"]
            po_number = f"PO-SD-{RUN}-{uuid.uuid4().hex[:6].upper()}"
            cur.execute(
                """
                INSERT INTO purchase_orders (po_number, supplier_id, product_id,
                                             quantity, unit_cost, status)
                VALUES (%s, %s, %s, 3, 1.0, %s) RETURNING id
                """,
                (po_number, supplier_id, product_id, status),
            )
            return cur.fetchone()["id"]


# ── migration artifacts ──────────────────────────────────────────────────────

def test_migration_columns_exist(app):
    with app.app_context():
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT table_name, data_type FROM information_schema.columns
                WHERE column_name = 'deleted_at'
                  AND table_name IN ('movements', 'purchase_orders')
                """
            )
            cols = {r["table_name"]: r["data_type"] for r in cur.fetchall()}
            assert cols.get("movements") == "timestamp without time zone"
            assert cols.get("purchase_orders") == "timestamp without time zone"
            cur.execute(
                """
                SELECT indexname FROM pg_indexes
                WHERE indexname IN ('idx_movements_active', 'idx_po_active')
                """
            )
            assert {r["indexname"] for r in cur.fetchall()} == {
                "idx_movements_active", "idx_po_active",
            }


# ── filtered reads ───────────────────────────────────────────────────────────

def test_soft_deleted_movement_excluded_from_recent(app):
    pid = _mk_product(app, stock=10)
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_movement_record(%s, 'IN', 5, 'sd', NULL, NULL)",
                        (pid,))
            mv_id = cur.fetchone()["sp_movement_record"]
            cur.execute("SELECT sp_movement_soft_delete(%s)", (mv_id,))

        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_movement_recent_for_product(%s)", (pid,))
            rows = cur.fetchall()
    assert rows == []  # soft-deleted movement hidden from the recent list


def test_soft_deleted_po_excluded_from_list_and_counts(app):
    pid = _mk_product(app)
    po_id = _mk_po(app, pid)
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM sp_po_list_by_status(NULL)")
            list_before = int(cur.fetchone()["c"])
            cur.execute("SELECT COALESCE(SUM(cnt), 0) AS c FROM sp_po_counts_by_status()")
            counts_before = int(cur.fetchone()["c"])

        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_po_soft_delete(%s)", (po_id,))

        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM sp_po_list_by_status(NULL)")
            list_after = int(cur.fetchone()["c"])
            cur.execute("SELECT COALESCE(SUM(cnt), 0) AS c FROM sp_po_counts_by_status()")
            counts_after = int(cur.fetchone()["c"])
            cur.execute(
                "SELECT COUNT(*) AS c FROM sp_po_list_by_status(NULL) "
                "WHERE id = %s", (po_id,),
            )
            assert int(cur.fetchone()["c"]) == 0

    assert list_after == list_before - 1
    assert counts_after == counts_before - 1


def test_po_transition_blocked_for_deleted(app):
    pid = _mk_product(app)
    po_id = _mk_po(app, pid)
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_po_soft_delete(%s)", (po_id,))
        with pytest.raises(Exception, match="not found"):
            with get_cursor(commit=True) as cur:
                cur.execute("SELECT sp_po_transition(%s, 'approved')", (po_id,))
        # PO still soft-deleted, status unchanged
        with get_cursor() as cur:
            cur.execute("SELECT status FROM purchase_orders WHERE id = %s", (po_id,))
            assert cur.fetchone()["status"] == "draft"


# ── phase 2: analytics exclude soft-deleted rows ─────────────────────────────

def test_soft_deleted_rows_excluded_from_analytics(app):
    pid = _mk_product(app, stock=10)
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT COALESCE(SUM(total), 0) AS t FROM sp_movement_daily_totals(1)")
            base = int(cur.fetchone()["t"])

        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_movement_record(%s, 'IN', 7, 'sd-pin', NULL, NULL)",
                        (pid,))
            mv_id = cur.fetchone()["sp_movement_record"]

        with get_cursor() as cur:
            cur.execute("SELECT COALESCE(SUM(total), 0) AS t FROM sp_movement_daily_totals(1)")
            assert int(cur.fetchone()["t"]) == base + 7

        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_movement_soft_delete(%s)", (mv_id,))

        # Phase 2: daily totals EXCLUDE the soft-deleted movement.
        with get_cursor() as cur:
            cur.execute("SELECT COALESCE(SUM(total), 0) AS t FROM sp_movement_daily_totals(1)")
            assert int(cur.fetchone()["t"]) == base


# ── phase 2: soft deletes write audit rows ───────────────────────────────────

def test_po_soft_delete_writes_audit_row(app):
    pid = _mk_product(app)
    po_id = _mk_po(app, pid)
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_po_soft_delete(%s)", (po_id,))
        with get_cursor() as cur:
            cur.execute(
                "SELECT action FROM audit_log "
                "WHERE target_type = 'purchase_order' AND target_id = %s "
                "AND action = 'po_deleted' ORDER BY id DESC LIMIT 1",
                (po_id,),
            )
            row = cur.fetchone()
    assert row is not None, "po_deleted audit row must exist after soft delete"


def test_movement_soft_delete_writes_audit_row(app):
    pid = _mk_product(app, stock=10)
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_movement_record(%s, 'IN', 3, 'sd-audit', NULL, NULL)",
                        (pid,))
            mv_id = cur.fetchone()["sp_movement_record"]
            cur.execute("SELECT sp_movement_soft_delete(%s)", (mv_id,))
        with get_cursor() as cur:
            cur.execute(
                "SELECT action FROM audit_log "
                "WHERE target_type = 'movement' AND target_id = %s "
                "AND action = 'movement_deleted' ORDER BY id DESC LIMIT 1",
                (mv_id,),
            )
            row = cur.fetchone()
    assert row is not None, "movement_deleted audit row must exist after soft delete"
