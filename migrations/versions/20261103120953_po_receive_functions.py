"""po_receive_functions

Revision ID: 20261103120953
Revises: 20261029125134
Create Date: 2026-11-03 12:09:53.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20261103120953"
down_revision = "20261029125134"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Drop the legacy 2-arg sp_po_transition to avoid overload ambiguity
    op.execute("DROP FUNCTION IF EXISTS sp_po_transition(integer, varchar);")

    # 2. Update sp_po_create to increment on_order for approved/in_transit POs
    op.execute("""
    CREATE OR REPLACE FUNCTION sp_po_create(
        p_po_number VARCHAR, p_supplier_id INT, p_product_id INT,
        p_quantity INT, p_unit_cost NUMERIC DEFAULT 0,
        p_status VARCHAR DEFAULT 'draft', p_eta_date DATE DEFAULT NULL
    ) RETURNS INT AS $$
    DECLARE
        new_id INT;
    BEGIN
        INSERT INTO purchase_orders (po_number, supplier_id, product_id, quantity, unit_cost, status, eta_date)
        VALUES (p_po_number, p_supplier_id, p_product_id, p_quantity, p_unit_cost, p_status, p_eta_date)
        RETURNING id INTO new_id;
        -- P0 (Batch1): POs born approved/in_transit contribute to on_order here;
        -- draft POs count only when sp_po_transition moves them to approved.
        IF p_status IN ('approved', 'in_transit') THEN
            UPDATE products
            SET on_order = on_order + p_quantity, updated_at = NOW()
            WHERE id = p_product_id;
        END IF;
        RETURN new_id;
    END;
    $$ LANGUAGE plpgsql;
    """)

    # 3. Create the canonical 7-arg sp_po_transition (receive-aware)
    op.execute("""
    CREATE OR REPLACE FUNCTION sp_po_transition(
        p_id INT,
        p_new_status VARCHAR,
        p_received_quantity INT DEFAULT NULL,
        p_received_by INT DEFAULT NULL,
        p_notes TEXT DEFAULT NULL,
        p_location VARCHAR(100) DEFAULT NULL,
        p_idempotency_key VARCHAR(64) DEFAULT NULL
    )
    RETURNS VOID AS $$
    DECLARE
        po purchase_orders%ROWTYPE;
        v_receive_qty INT;
        v_receipt_id BIGINT;
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

        IF po.product_id IS NOT NULL AND p_new_status = 'approved' THEN
            -- on_order counts approved/in_transit open POs only.
            UPDATE products
            SET on_order = on_order + po.quantity,
                updated_at = NOW()
            WHERE id = po.product_id;
        ELSIF po.product_id IS NOT NULL AND p_new_status = 'received' THEN
            v_receive_qty := COALESCE(p_received_quantity, po.quantity);

            -- Validate: positive and not exceeding outstanding
            IF v_receive_qty <= 0 THEN
                RAISE EXCEPTION 'Receive quantity must be positive';
            END IF;
            IF v_receive_qty > (po.quantity - COALESCE(po.received_quantity, 0)) THEN
                RAISE EXCEPTION 'Receive quantity % exceeds outstanding %',
                    v_receive_qty, (po.quantity - COALESCE(po.received_quantity, 0));
            END IF;

            -- Receipt insert FIRST: a duplicate idempotency key aborts here,
            -- before any stock/movement/on_order effect is applied.
            IF p_received_by IS NOT NULL THEN
                v_receipt_id := sp_goods_receipt_create(
                    po.id, v_receive_qty, p_received_by,
                    p_notes, p_location, p_idempotency_key
                );
                IF p_idempotency_key IS NOT NULL AND v_receipt_id IS NULL THEN
                    -- Key exists: verify it's a true replay (same PO + qty).
                    -- If payload differs, it's a client bug, not a replay.
                    PERFORM 1 FROM goods_receipts gr
                    WHERE gr.idempotency_key = p_idempotency_key
                      AND gr.po_id = po.id
                      AND gr.quantity = v_receive_qty;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'Idempotency key % reused with different PO/quantity', p_idempotency_key;
                    END IF;
                    RETURN;  -- true replay: nothing applied yet, so nothing to undo
                END IF;
            END IF;

            UPDATE purchase_orders
            SET received_quantity = COALESCE(received_quantity, 0) + v_receive_qty
            WHERE id = p_id;

            -- DB-024: route through the atomic movement funnel (ledger + stock delta)
            PERFORM sp_movement_record(
                po.product_id, 'IN', v_receive_qty,
                po.po_number, 'PO received', p_received_by
            );

            UPDATE products
            SET on_order = GREATEST(on_order - v_receive_qty, 0),
                updated_at = NOW()
            WHERE id = po.product_id;
        ELSIF po.product_id IS NOT NULL AND p_new_status = 'cancelled' THEN
            -- Only open (approved/in_transit) POs contributed to on_order: a draft
            -- cancel must not steal another PO's contribution, and a cancel after
            -- a partial receipt releases only the unreceived remainder.
            IF po.status IN ('approved', 'in_transit') THEN
                UPDATE products
                SET on_order = GREATEST(on_order - (po.quantity - COALESCE(po.received_quantity, 0)), 0),
                    updated_at = NOW()
                WHERE id = po.product_id;
            END IF;
        END IF;

        -- Conditional status update: partial receipt stays in_transit, full receipt becomes received
        IF po.status = 'in_transit' AND p_new_status = 'received' THEN
            UPDATE purchase_orders
            SET status = CASE
                WHEN COALESCE(received_quantity, 0) >= quantity THEN 'received'
                ELSE 'in_transit'
            END,
            updated_at = NOW()
            WHERE id = p_id;
        ELSE
            UPDATE purchase_orders SET status = p_new_status, updated_at = NOW() WHERE id = p_id;
        END IF;
    END;
    $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    # Restore the old 2-arg sp_po_transition (legacy behavior, full receipt, no goods_receipts)
    op.execute("""
    DROP FUNCTION IF EXISTS sp_po_transition(
        integer, varchar, integer, integer, text, varchar, varchar
    );
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
            RETURN;
        END IF;
        IF NOT (
            (po.status = 'draft'       AND p_new_status IN ('approved', 'cancelled')) OR
            (po.status = 'approved'    AND p_new_status IN ('in_transit', 'cancelled')) OR
            (po.status = 'in_transit'  AND p_new_status IN ('received', 'cancelled'))
        ) THEN
            RAISE EXCEPTION 'Invalid PO transition: % -> %', po.status, p_new_status;
        END IF;

        IF po.product_id IS NOT NULL AND p_new_status = 'received' THEN
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
    """)

    # Restore sp_po_create without on_order effects
    op.execute("""
    CREATE OR REPLACE FUNCTION sp_po_create(
        p_po_number VARCHAR, p_supplier_id INT, p_product_id INT,
        p_quantity INT, p_unit_cost NUMERIC DEFAULT 0,
        p_status VARCHAR DEFAULT 'draft', p_eta_date DATE DEFAULT NULL
    ) RETURNS INT AS $$
    DECLARE
        new_id INT;
    BEGIN
        INSERT INTO purchase_orders (po_number, supplier_id, product_id, quantity, unit_cost, status, eta_date)
        VALUES (p_po_number, p_supplier_id, p_product_id, p_quantity, p_unit_cost, p_status, p_eta_date)
        RETURNING id INTO new_id;
        RETURN new_id;
    END;
    $$ LANGUAGE plpgsql;
    """)