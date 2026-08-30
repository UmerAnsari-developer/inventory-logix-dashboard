"""Fix critical issues: movement validation trigger, ADJUSTMENT check, timezone.

Revision ID: 002_critical_fixes
Revises: 001_initial
Create Date: 2026-08-29
"""
from pathlib import Path
from alembic import op
import sqlalchemy as sa

revision = "002_critical_fixes"
down_revision = "001_initial"
branch_labels = None
depends_on = None

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "app" / "database"


def upgrade() -> None:
    # Fix #1: Add movement validation trigger (auto-populate SKU, prevent negative stock)
    op.execute("""
        CREATE OR REPLACE FUNCTION trg_validate_movement()
        RETURNS TRIGGER AS $$
        DECLARE
            v_sku VARCHAR;
            v_stock INT;
        BEGIN
            SELECT sku, current_stock INTO v_sku, v_stock FROM products WHERE id = NEW.product_id;
            IF v_sku IS NULL THEN
                RAISE EXCEPTION 'Invalid product_id %: product does not exist', NEW.product_id;
            END IF;
            NEW.sku := v_sku;
            IF NEW.type = 'OUT' AND v_stock - NEW.quantity < 0 THEN
                RAISE EXCEPTION 'Insufficient stock: have %, need %', v_stock, NEW.quantity;
            END IF;
            IF NEW.type = 'ADJUSTMENT' AND v_stock + NEW.quantity < 0 THEN
                RAISE EXCEPTION 'Adjustment would create negative stock: have %, adjustment %', v_stock, NEW.quantity;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        DROP TRIGGER IF EXISTS trg_validate_movement ON movements;
        CREATE TRIGGER trg_validate_movement
            BEFORE INSERT ON movements
            FOR EACH ROW
            EXECUTE FUNCTION trg_validate_movement();
    """)

    # Fix #4: Fix timezone in etl_state
    op.execute("""
        ALTER TABLE etl_state
        ALTER COLUMN updated_at SET DATA TYPE TIMESTAMP
        USING updated_at AT TIME ZONE 'UTC';
    """)

    op.execute("""
        ALTER TABLE etl_state
        ALTER COLUMN updated_at SET DEFAULT (NOW() AT TIME ZONE 'UTC');
    """)

    # Fix #4: Fix timezone in etl_warehouse_state (if exists)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'etl_warehouse_state') THEN
                ALTER TABLE etl_warehouse_state
                ALTER COLUMN updated_at SET DATA TYPE TIMESTAMP
                USING updated_at AT TIME ZONE 'UTC';
                ALTER TABLE etl_warehouse_state
                ALTER COLUMN updated_at SET DEFAULT (NOW() AT TIME ZONE 'UTC');
            END IF;
        END $$;
    """)

    # Fix #5: Add ADJUSTMENT validation to movement service (Python-side, no DB change needed)
    # The trigger already handles this at DB level


def downgrade() -> None:
    # Remove movement validation trigger
    op.execute("DROP TRIGGER IF EXISTS trg_validate_movement ON movements CASCADE")
    op.execute("DROP FUNCTION IF EXISTS trg_validate_movement() CASCADE")

    # Revert timezone changes
    op.execute("""
        ALTER TABLE etl_state
        ALTER COLUMN updated_at SET DATA TYPE TIMESTAMPTZ
        USING updated_at AT TIME ZONE 'UTC';
    """)
