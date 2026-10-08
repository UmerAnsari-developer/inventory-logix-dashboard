"""db_integrity_batch3_schema_ddl

Revision ID: 143bebd480ec
Revises: 20260925_db_integrity_fixes
Create Date: 2026-09-25 20:33:00.504420
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = '143bebd480ec'
down_revision = '20260925_db_integrity_fixes'
branch_labels = None
depends_on = None


def _run(conn, sql: str):
    """Execute raw SQL that may contain % placeholders."""
    conn.execute(text(sql))


def upgrade() -> None:
    conn = op.get_bind()

    # DB-035: movements.product_id CASCADE -> RESTRICT
    _run(conn, """
        DO $$
        DECLARE c TEXT;
        BEGIN
            SELECT conname INTO c
              FROM pg_constraint
             WHERE conrelid = 'movements'::regclass
               AND contype = 'f'
               AND conkey = ARRAY[(SELECT attnum FROM pg_attribute
                                    WHERE attrelid = 'movements'::regclass
                                      AND attname = 'product_id')];
            IF c IS NOT NULL THEN
                EXECUTE format('ALTER TABLE movements DROP CONSTRAINT %I', c);
            END IF;
            ALTER TABLE movements ADD CONSTRAINT movements_product_id_fkey
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT;
        END $$;
    """)

    # DB-036: movements.user_id SET NULL -> RESTRICT
    _run(conn, """
        DO $$
        DECLARE c TEXT;
        BEGIN
            SELECT conname INTO c
              FROM pg_constraint
             WHERE conrelid = 'movements'::regclass
               AND contype = 'f'
               AND conkey = ARRAY[(SELECT attnum FROM pg_attribute
                                    WHERE attrelid = 'movements'::regclass
                                      AND attname = 'user_id')];
            IF c IS NOT NULL THEN
                EXECUTE format('ALTER TABLE movements DROP CONSTRAINT %I', c);
            END IF;
            ALTER TABLE movements ADD CONSTRAINT movements_user_id_fkey
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT;
        END $$;
    """)

    # DB-036: audit_log.user_id SET NULL -> RESTRICT
    _run(conn, """
        DO $$
        DECLARE c TEXT;
        BEGIN
            SELECT conname INTO c
              FROM pg_constraint
             WHERE conrelid = 'audit_log'::regclass
               AND contype = 'f'
               AND conkey = ARRAY[(SELECT attnum FROM pg_attribute
                                    WHERE attrelid = 'audit_log'::regclass
                                      AND attname = 'user_id')];
            IF c IS NOT NULL THEN
                EXECUTE format('ALTER TABLE audit_log DROP CONSTRAINT %I', c);
            END IF;
            ALTER TABLE audit_log ADD CONSTRAINT audit_log_user_id_fkey
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT;
        END $$;
    """)

    # DB-037: purchase_orders.supplier_id SET NULL -> NOT NULL + RESTRICT
    # Pre-check: must have no NULL supplier_id
    _run(conn, """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM purchase_orders WHERE supplier_id IS NULL) THEN
                RAISE EXCEPTION 'DB-037 blocked: NULL supplier_id rows exist';
            END IF;
        END $$;
    """)
    _run(conn, """
        DO $$
        DECLARE c TEXT;
        BEGIN
            SELECT conname INTO c
              FROM pg_constraint
             WHERE conrelid = 'purchase_orders'::regclass
               AND contype = 'f'
               AND conkey = ARRAY[(SELECT attnum FROM pg_attribute
                                    WHERE attrelid = 'purchase_orders'::regclass
                                      AND attname = 'supplier_id')];
            IF c IS NOT NULL THEN
                EXECUTE format('ALTER TABLE purchase_orders DROP CONSTRAINT %I', c);
            END IF;
            ALTER TABLE purchase_orders ALTER COLUMN supplier_id SET NOT NULL;
            ALTER TABLE purchase_orders ADD CONSTRAINT purchase_orders_supplier_id_fkey
                FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE RESTRICT;
        END $$;
    """)

    # DB-037: purchase_orders.product_id SET NULL -> NOT NULL + RESTRICT
    _run(conn, """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM purchase_orders WHERE product_id IS NULL) THEN
                RAISE EXCEPTION 'DB-037 blocked: NULL product_id rows exist';
            END IF;
        END $$;
    """)
    _run(conn, """
        DO $$
        DECLARE c TEXT;
        BEGIN
            SELECT conname INTO c
              FROM pg_constraint
             WHERE conrelid = 'purchase_orders'::regclass
               AND contype = 'f'
               AND conkey = ARRAY[(SELECT attnum FROM pg_attribute
                                    WHERE attrelid = 'purchase_orders'::regclass
                                      AND attname = 'product_id')];
            IF c IS NOT NULL THEN
                EXECUTE format('ALTER TABLE purchase_orders DROP CONSTRAINT %I', c);
            END IF;
            ALTER TABLE purchase_orders ALTER COLUMN product_id SET NOT NULL;
            ALTER TABLE purchase_orders ADD CONSTRAINT purchase_orders_product_id_fkey
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT;
        END $$;
    """)

    # DB-047: Check constraints for products (already in schema.sql, but ensure they exist)
    _run(conn, """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'products' AND constraint_name = 'chk_current_stock_nonnegative'
            ) THEN
                ALTER TABLE products ADD CONSTRAINT chk_current_stock_nonnegative CHECK (current_stock >= 0);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'products' AND constraint_name = 'chk_reorder_point_nonnegative'
            ) THEN
                ALTER TABLE products ADD CONSTRAINT chk_reorder_point_nonnegative CHECK (reorder_point >= 0);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'products' AND constraint_name = 'chk_demand_rate_nonnegative'
            ) THEN
                ALTER TABLE products ADD CONSTRAINT chk_demand_rate_nonnegative CHECK (demand_rate >= 0);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'products' AND constraint_name = 'chk_ordering_cost_nonnegative'
            ) THEN
                ALTER TABLE products ADD CONSTRAINT chk_ordering_cost_nonnegative CHECK (ordering_cost >= 0);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'products' AND constraint_name = 'chk_holding_cost_nonnegative'
            ) THEN
                ALTER TABLE products ADD CONSTRAINT chk_holding_cost_nonnegative CHECK (holding_cost >= 0);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'products' AND constraint_name = 'chk_unit_price_nonnegative'
            ) THEN
                ALTER TABLE products ADD CONSTRAINT chk_unit_price_nonnegative CHECK (unit_price >= 0);
            END IF;
        END $$;
    """)

    # DB-047: Check constraints for suppliers
    _run(conn, """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'suppliers' AND constraint_name = 'chk_lead_days_nonnegative'
            ) THEN
                ALTER TABLE suppliers ADD CONSTRAINT chk_lead_days_nonnegative CHECK (lead_days >= 0);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'suppliers' AND constraint_name = 'chk_spend_amount_nonnegative'
            ) THEN
                ALTER TABLE suppliers ADD CONSTRAINT chk_spend_amount_nonnegative CHECK (spend_amount >= 0);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'suppliers' AND constraint_name = 'chk_reliability_range'
            ) THEN
                ALTER TABLE suppliers ADD CONSTRAINT chk_reliability_range CHECK (reliability BETWEEN 0 AND 100);
            END IF;
        END $$;
    """)

    # DB-054: Check constraints for purchase_orders (quantity > 0, unit_cost >= 0)
    _run(conn, """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'purchase_orders' AND constraint_name = 'chk_po_quantity_positive'
            ) THEN
                ALTER TABLE purchase_orders ADD CONSTRAINT chk_po_quantity_positive CHECK (quantity > 0);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'purchase_orders' AND constraint_name = 'chk_po_unit_cost_nonnegative'
            ) THEN
                ALTER TABLE purchase_orders ADD CONSTRAINT chk_po_unit_cost_nonnegative CHECK (unit_cost >= 0);
            END IF;
        END $$;
    """)

    # DB-080: Partial unique index on products.sku WHERE deleted_at IS NULL
    _run(conn, """
        DO $$
        BEGIN
            IF to_regclass('products_sku_live_key') IS NULL THEN
                -- Dedup live rows only
                UPDATE products p
                   SET sku = LEFT(p.sku, 44) || '#' || p.id
                 WHERE p.deleted_at IS NULL
                   AND EXISTS (
                       SELECT 1 FROM products q
                        WHERE q.sku = p.sku
                          AND q.deleted_at IS NULL
                          AND q.id < p.id);
                CREATE UNIQUE INDEX products_sku_live_key
                    ON products (sku)
                    WHERE deleted_at IS NULL;
                ALTER TABLE products DROP CONSTRAINT IF EXISTS products_sku_key;
            END IF;
        END $$;
    """)

    # DB-084: Assert FK policies for notifications, system_backups, system_config_overrides, scheduled_audit_reports
    _run(conn, """
        DO $$
        DECLARE bad TEXT;
        BEGIN
            SELECT string_agg(conrelid::regclass::text || '.' || conname, ', ') INTO bad
              FROM pg_constraint
             WHERE contype = 'f'
               AND conrelid = ANY(ARRAY['notifications','system_backups',
                       'system_config_overrides','scheduled_audit_reports']::regclass[])
               AND confrelid = 'users'::regclass
               AND confdeltype <> 'a';   -- 'a' = NO ACTION
            IF bad IS NOT NULL THEN
                RAISE EXCEPTION 'DB-084 drift: expected NO ACTION, found %', bad;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    conn = op.get_bind()

    # DB-080: Drop partial index, restore full constraint
    _run(conn, """
        DROP INDEX IF EXISTS products_sku_live_key;
        -- Note: we don't re-add the full constraint here because it would fail on existing duplicates
        -- The downgrade is intentionally one-way for this change
    """)

    # DB-037: Revert purchase_orders FKs to SET NULL (drop NOT NULL)
    _run(conn, """
        ALTER TABLE purchase_orders DROP CONSTRAINT IF EXISTS purchase_orders_supplier_id_fkey;
        ALTER TABLE purchase_orders DROP CONSTRAINT IF EXISTS purchase_orders_product_id_fkey;
        ALTER TABLE purchase_orders ALTER COLUMN supplier_id DROP NOT NULL;
        ALTER TABLE purchase_orders ALTER COLUMN product_id DROP NOT NULL;
        ALTER TABLE purchase_orders ADD CONSTRAINT purchase_orders_supplier_id_fkey
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL;
        ALTER TABLE purchase_orders ADD CONSTRAINT purchase_orders_product_id_fkey
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL;
    """)

    # DB-036: Revert audit_log.user_id to SET NULL
    _run(conn, """
        ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_user_id_fkey;
        ALTER TABLE audit_log ADD CONSTRAINT audit_log_user_id_fkey
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;
    """)

    # DB-035/036: Revert movements FKs
    _run(conn, """
        ALTER TABLE movements DROP CONSTRAINT IF EXISTS movements_product_id_fkey;
        ALTER TABLE movements DROP CONSTRAINT IF EXISTS movements_user_id_fkey;
        ALTER TABLE movements ADD CONSTRAINT movements_product_id_fkey
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE;
        ALTER TABLE movements ADD CONSTRAINT movements_user_id_fkey
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;
    """)

    # DB-047/054: Drop check constraints
    _run(conn, """
        ALTER TABLE products DROP CONSTRAINT IF EXISTS chk_current_stock_nonnegative;
        ALTER TABLE products DROP CONSTRAINT IF EXISTS chk_reorder_point_nonnegative;
        ALTER TABLE products DROP CONSTRAINT IF EXISTS chk_demand_rate_nonnegative;
        ALTER TABLE products DROP CONSTRAINT IF EXISTS chk_ordering_cost_nonnegative;
        ALTER TABLE products DROP CONSTRAINT IF EXISTS chk_holding_cost_nonnegative;
        ALTER TABLE products DROP CONSTRAINT IF EXISTS chk_unit_price_nonnegative;
        ALTER TABLE suppliers DROP CONSTRAINT IF EXISTS chk_lead_days_nonnegative;
        ALTER TABLE suppliers DROP CONSTRAINT IF EXISTS chk_spend_amount_nonnegative;
        ALTER TABLE suppliers DROP CONSTRAINT IF EXISTS chk_reliability_range;
        ALTER TABLE purchase_orders DROP CONSTRAINT IF EXISTS chk_po_quantity_positive;
        ALTER TABLE purchase_orders DROP CONSTRAINT IF EXISTS chk_po_unit_cost_nonnegative;
    """)