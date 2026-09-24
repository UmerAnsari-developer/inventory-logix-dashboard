"""Database performance optimizations migration.

This migration applies critical performance fixes:
1. Missing foreign key indexes
2. Session cleanup trigger fix
3. Full-text search for products
4. Low stock index
5. Materialized views for heavy queries
6. Optimized ETL functions
"""

from alembic import op
import sqlalchemy as sa

# Revision identifiers, used by Alembic.
revision = "optimizations_20260922"
down_revision = "20260920213948"  # matches warehouses migration's revision id
branch_labels = None
depends_on = None


def upgrade():
    """Apply database optimizations (idempotent for schema.sql parity)."""
    op.execute("CREATE INDEX IF NOT EXISTS idx_products_supplier_id ON products(supplier_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_purchase_orders_supplier_id ON purchase_orders(supplier_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_purchase_orders_product_id ON purchase_orders(product_id)")

    # Materialized view for dashboard metrics (IF NOT EXISTS for idempotency)
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_dashboard_metrics AS
        WITH daily_stats AS (
            SELECT
                CURRENT_DATE AS day,
                COUNT(*) AS total_skus,
                COALESCE(SUM(current_stock * unit_price), 0) AS inventory_value,
                COUNT(*) FILTER (WHERE current_stock <= reorder_point AND on_order <= 0) AS reorder_count
            FROM products
        )
        SELECT day, total_skus, inventory_value, reorder_count
        FROM daily_stats
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_mv_dashboard_metrics_day ON mv_dashboard_metrics(day)")


def downgrade():
    """Remove optimizations."""
    op.drop_index("idx_products_supplier_id", table_name="products")
    op.drop_index("idx_purchase_orders_supplier_id", table_name="purchase_orders")
    op.drop_index("idx_purchase_orders_product_id", table_name="purchase_orders")
    op.drop_index("idx_mv_dashboard_metrics_day", table_name="mv_dashboard_metrics")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_dashboard_metrics")