"""DB-021: drop legacy 11-param sp_product_update overload (ambiguous with NULL args).

Revision ID: 20260926_drop_sp_product_update_legacy
Revises: 876e02bdc941
Create Date: 2026-09-26
"""
from alembic import op

revision = "20260926_drop_sp_product_update_legacy"
down_revision = "876e02bdc941"
branch_labels = None
depends_on = None

# Legacy signature (had p_current_stock between supplier_id and reorder_point)
_LEGACY = (
    "sp_product_update(integer, character varying, character varying, "
    "character varying, numeric, integer, integer, integer, "
    "numeric, numeric, numeric)"
)


def upgrade() -> None:
    # Drop the legacy 11-param overload; the 10-param version (no current_stock)
    # is the only remaining signature, so calls with NULL args are unambiguous.
    op.execute(f"DROP FUNCTION IF EXISTS {_LEGACY};")


def downgrade() -> None:
    # Recreate the legacy overload as a no-op stub so downgrade() is complete.
    # It must NOT write current_stock (DB-021 invariant preserved).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sp_product_update(
            p_id INT, p_name VARCHAR, p_category VARCHAR DEFAULT '',
            p_warehouse VARCHAR DEFAULT 'WH-Pune', p_unit_price NUMERIC DEFAULT 0,
            p_supplier_id INT DEFAULT NULL, p_current_stock INT DEFAULT 0,
            p_reorder_point INT DEFAULT 0, p_demand_rate NUMERIC DEFAULT 0,
            p_ordering_cost NUMERIC DEFAULT 0, p_holding_cost NUMERIC DEFAULT 0
        ) RETURNS VOID AS $$
        BEGIN
            -- DB-021: current_stock intentionally NOT updated (legacy stub).
            UPDATE products SET
                name = p_name, category = p_category, warehouse = p_warehouse,
                unit_price = p_unit_price, supplier_id = p_supplier_id,
                reorder_point = p_reorder_point,
                demand_rate = p_demand_rate, ordering_cost = p_ordering_cost,
                holding_cost = p_holding_cost, updated_at = NOW()
            WHERE id = p_id;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
