"""GAP-020 phase 1: soft delete for movements + purchase_orders.

Revision ID: 20261012_soft_delete_ops
Revises: 20261012_model_baselines
Create Date: 2026-10-12

- deleted_at TIMESTAMP on movements + purchase_orders (mirrors products pattern)
- Partial indexes: soft-deleted rows never enter the active-scan indexes
- sp_movement_soft_delete / sp_po_soft_delete (mirror sp_product_delete)
- Filtered reads (phase-1 boundary — user-facing lists only):
    sp_po_list_by_status, sp_po_counts_by_status, sp_movement_recent_for_product
- Guard: sp_po_transition SELECT ... FOR UPDATE excludes deleted rows
- Analytics/dashboard/reports/ETL stay UNFILTERED until phase 2 (documented in
  README known limitations; pinned by tests/test_soft_delete.py).

sp_po_list_by_status previously used SELECT po.* — adding deleted_at would
break its declared RETURNS TABLE, so the filtered body lists columns explicitly.
Downgrade restores the ORIGINAL proc bodies verbatim BEFORE dropping the
columns (a filter referencing a dropped column would error otherwise).
"""
from alembic import op

revision = "20261012_soft_delete_ops"
down_revision = "20261012_model_baselines"
branch_labels = None
depends_on = None

_COLUMNS = """
ALTER TABLE movements ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_movements_active
    ON movements (product_id, created_at) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_po_active
    ON purchase_orders (status, created_at) WHERE deleted_at IS NULL;
"""

_SOFT_DELETE_PROCS = """
CREATE OR REPLACE FUNCTION sp_movement_soft_delete(p_id INT)
RETURNS VOID AS $$
BEGIN
    UPDATE movements SET deleted_at = NOW() WHERE id = p_id AND deleted_at IS NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_po_soft_delete(p_id INT)
RETURNS VOID AS $$
BEGIN
    UPDATE purchase_orders SET deleted_at = NOW() WHERE id = p_id AND deleted_at IS NULL;
END;
$$ LANGUAGE plpgsql;
"""

# Filtered bodies — copied verbatim from procedures.sql + `AND deleted_at IS NULL`.
# sp_po_list_by_status: explicit column list (po.* would now include deleted_at
# and break the declared RETURNS TABLE).
_FILTERED_PROCS = """
CREATE OR REPLACE FUNCTION sp_movement_recent_for_product(
    p_product_id INT, p_limit INT DEFAULT 10
) RETURNS TABLE (
    id INT, type VARCHAR, quantity INT, reference VARCHAR, notes TEXT,
    created_at TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT m.id, m.type, m.quantity, m.reference, m.notes,
           to_char(m.created_at, 'YYYY-MM-DD HH24:MI') AS created_at
    FROM movements m
    WHERE m.product_id = p_product_id
      AND m.deleted_at IS NULL
    ORDER BY m.created_at DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_po_list_by_status(p_status VARCHAR DEFAULT NULL)
RETURNS TABLE (
    id INT, po_number VARCHAR, supplier_id INT, product_id INT,
    quantity INT, unit_cost NUMERIC, status VARCHAR, eta_date DATE,
    created_at TIMESTAMP, updated_at TIMESTAMP,
    supplier_name VARCHAR, product_name VARCHAR, sku VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT po.id, po.po_number, po.supplier_id, po.product_id,
           po.quantity, po.unit_cost, po.status, po.eta_date,
           po.created_at, po.updated_at,
           s.name AS supplier_name, p.name AS product_name, p.sku
    FROM purchase_orders po
    LEFT JOIN suppliers s ON s.id = po.supplier_id
    LEFT JOIN products p ON p.id = po.product_id
    WHERE po.deleted_at IS NULL
      AND (p_status IS NULL OR p_status = 'all' OR po.status = p_status)
    ORDER BY po.created_at DESC;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_po_counts_by_status()
RETURNS TABLE(status VARCHAR, cnt BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT po.status, COUNT(*) AS cnt
    FROM purchase_orders po
    WHERE po.deleted_at IS NULL
    GROUP BY po.status;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_po_transition(p_id INT, p_new_status VARCHAR)
RETURNS VOID AS $$
DECLARE
    po purchase_orders%ROWTYPE;
BEGIN
    SELECT * INTO po FROM purchase_orders
    WHERE id = p_id AND deleted_at IS NULL
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Purchase order % not found', p_id;
    END IF;
    IF po.status = p_new_status THEN
        RETURN;  -- idempotent re-apply
    END IF;
    IF NOT (
        (po.status = 'draft'       AND p_new_status IN ('approved', 'cancelled')) OR
        (po.status = 'approved'    AND p_new_status IN ('in_transit', 'cancelled')) OR
        (po.status = 'in_transit'  AND p_new_status IN ('received', 'cancelled'))
    ) THEN
        RAISE EXCEPTION 'Invalid PO transition: % -> %', po.status, p_new_status;
    END IF;

    IF po.product_id IS NOT NULL AND p_new_status = 'received' THEN
        -- DB-024: route through the atomic movement funnel (ledger + stock delta)
        PERFORM sp_movement_record(po.product_id, 'IN', po.quantity,
                                   po.po_number, 'PO received', NULL);
        UPDATE products
        SET on_order = GREATEST(on_order - po.quantity, 0),
            updated_at = NOW()
        WHERE id = po.product_id;
    ELSIF po.product_id IS NOT NULL AND p_new_status = 'cancelled' THEN
        UPDATE products
        SET on_order = GREATEST(on_order - po.quantity, 0),
            updated_at = NOW()
        WHERE id = po.product_id;
    END IF;

    UPDATE purchase_orders SET status = p_new_status, updated_at = NOW() WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;
"""

# Original bodies verbatim (pre-soft-delete) — restored on downgrade BEFORE the
# columns drop, otherwise the filters reference a nonexistent column.
_ORIGINAL_PROCS = """
CREATE OR REPLACE FUNCTION sp_movement_recent_for_product(
    p_product_id INT, p_limit INT DEFAULT 10
) RETURNS TABLE (
    id INT, type VARCHAR, quantity INT, reference VARCHAR, notes TEXT,
    created_at TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT m.id, m.type, m.quantity, m.reference, m.notes,
           to_char(m.created_at, 'YYYY-MM-DD HH24:MI') AS created_at
    FROM movements m
    WHERE m.product_id = p_product_id
    ORDER BY m.created_at DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_po_list_by_status(p_status VARCHAR DEFAULT NULL)
RETURNS TABLE (
    id INT, po_number VARCHAR, supplier_id INT, product_id INT,
    quantity INT, unit_cost NUMERIC, status VARCHAR, eta_date DATE,
    created_at TIMESTAMP, updated_at TIMESTAMP,
    supplier_name VARCHAR, product_name VARCHAR, sku VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT po.*, s.name AS supplier_name, p.name AS product_name, p.sku
    FROM purchase_orders po
    LEFT JOIN suppliers s ON s.id = po.supplier_id
    LEFT JOIN products p ON p.id = po.product_id
    WHERE (p_status IS NULL OR p_status = 'all' OR po.status = p_status)
    ORDER BY po.created_at DESC;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_po_counts_by_status()
RETURNS TABLE(status VARCHAR, cnt BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT po.status, COUNT(*) AS cnt
    FROM purchase_orders po
    GROUP BY po.status;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_po_transition(p_id INT, p_new_status VARCHAR)
RETURNS VOID AS $$
DECLARE
    po purchase_orders%ROWTYPE;
BEGIN
    SELECT * INTO po FROM purchase_orders WHERE id = p_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Purchase order % not found', p_id;
    END IF;
    IF po.status = p_new_status THEN
        RETURN;  -- idempotent re-apply
    END IF;
    IF NOT (
        (po.status = 'draft'       AND p_new_status IN ('approved', 'cancelled')) OR
        (po.status = 'approved'    AND p_new_status IN ('in_transit', 'cancelled')) OR
        (po.status = 'in_transit'  AND p_new_status IN ('received', 'cancelled'))
    ) THEN
        RAISE EXCEPTION 'Invalid PO transition: % -> %', po.status, p_new_status;
    END IF;

    IF po.product_id IS NOT NULL AND p_new_status = 'received' THEN
        -- DB-024: route through the atomic movement funnel (ledger + stock delta)
        PERFORM sp_movement_record(po.product_id, 'IN', po.quantity,
                                   po.po_number, 'PO received', NULL);
        UPDATE products
        SET on_order = GREATEST(on_order - po.quantity, 0),
            updated_at = NOW()
        WHERE id = po.product_id;
    ELSIF po.product_id IS NOT NULL AND p_new_status = 'cancelled' THEN
        UPDATE products
        SET on_order = GREATEST(on_order - po.quantity, 0),
            updated_at = NOW()
        WHERE id = po.product_id;
    END IF;

    UPDATE purchase_orders SET status = p_new_status, updated_at = NOW() WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;
"""

_DROP_PROCS = """
DROP FUNCTION IF EXISTS sp_movement_soft_delete(INT);
DROP FUNCTION IF EXISTS sp_po_soft_delete(INT);
"""

_DROP_INDEXES = """
DROP INDEX IF EXISTS idx_movements_active;
DROP INDEX IF EXISTS idx_po_active;
"""

_DROP_COLUMNS = """
ALTER TABLE movements DROP COLUMN IF EXISTS deleted_at;
ALTER TABLE purchase_orders DROP COLUMN IF EXISTS deleted_at;
"""


def upgrade() -> None:
    op.execute(_COLUMNS)
    op.execute(_INDEXES)
    op.execute(_SOFT_DELETE_PROCS)
    op.execute(_FILTERED_PROCS)


def downgrade() -> None:
    op.execute(_ORIGINAL_PROCS)
    op.execute(_DROP_PROCS)
    op.execute(_DROP_INDEXES)
    op.execute(_DROP_COLUMNS)
