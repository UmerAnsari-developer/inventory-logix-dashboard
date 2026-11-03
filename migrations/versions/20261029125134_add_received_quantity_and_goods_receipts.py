"""add_received_quantity_and_goods_receipts

Revision ID: 20261029125134
Revises: 20261018_drop_forecast_tables
Create Date: 2026-10-29T12:51:34.123456
"""
from alembic import op
import sqlalchemy as sa

revision = "20261029125134"
down_revision = "20261022_sessions_active_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add received_quantity to purchase_orders (nullable, default NULL)
    op.add_column(
        "purchase_orders",
        sa.Column("received_quantity", sa.Integer(), nullable=True)
    )
    
    # Backfill existing received POs
    op.execute("""
        UPDATE purchase_orders
        SET received_quantity = quantity
        WHERE status = 'received' AND received_quantity IS NULL
    """)
    
    # Add check constraints
    op.create_check_constraint(
        "chk_po_received_qty_nonneg",
        "purchase_orders",
        "received_quantity IS NULL OR received_quantity >= 0"
    )
    op.create_check_constraint(
        "chk_po_received_lte_ordered",
        "purchase_orders",
        "received_quantity IS NULL OR received_quantity <= quantity"
    )
    
    # 2. Create goods_receipts table
    op.create_table(
        "goods_receipts",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("po_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("received_by", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("location", sa.String(100), nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="goods_receipts_pkey"),
        sa.ForeignKeyConstraint(["po_id"], ["purchase_orders.id"], ondelete="RESTRICT", name="fk_gr_po"),
        sa.ForeignKeyConstraint(["received_by"], ["users.id"], ondelete="RESTRICT", name="fk_gr_received_by"),
        sa.CheckConstraint("quantity > 0", name="chk_gr_quantity_positive"),
        sa.UniqueConstraint("idempotency_key", name="uq_gr_idempotency_key"),
    )
    
    # Indexes
    op.create_index("idx_gr_po", "goods_receipts", ["po_id"])
    op.create_index("idx_gr_received_at", "goods_receipts", ["received_at"])
    op.create_index("idx_gr_received_by", "goods_receipts", ["received_by"])
    op.create_index(
        "idx_gr_idempotency",
        "goods_receipts",
        ["idempotency_key"],
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        unique=True
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("idx_gr_idempotency", table_name="goods_receipts")
    op.drop_index("idx_gr_received_by", table_name="goods_receipts")
    op.drop_index("idx_gr_received_at", table_name="goods_receipts")
    op.drop_index("idx_gr_po", table_name="goods_receipts")
    
    # Drop table
    op.drop_table("goods_receipts")
    
    # Drop constraints
    op.drop_constraint("chk_po_received_lte_ordered", "purchase_orders", type_="check")
    op.drop_constraint("chk_po_received_qty_nonneg", "purchase_orders", type_="check")
    
    # Drop column
    op.drop_column("purchase_orders", "received_quantity")