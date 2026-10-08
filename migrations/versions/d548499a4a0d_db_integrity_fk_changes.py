"""db_integrity_fk_changes

Revision ID: d548499a4a0d
Revises: 68536c7cf9f3
Create Date: 2026-09-25 23:00:01.663607
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = 'd548499a4a0d'
down_revision = '68536c7cf9f3'
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
    # Pre-check: must have no NULL product_id
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


def downgrade() -> None:
    conn = op.get_bind()

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