"""goods_receipts_indexes_concurrently

Revision ID: 20261103223139
Revises: 20261103120953
Create Date: 2026-11-03 22:31:39.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20261103223139"
down_revision = "20261103120953"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # These indexes were created in the goods_receipts migration but not CONCURRENTLY.
    # For production, we recreate them CONCURRENTLY to avoid locking.
    # CONCURRENTLY requires autocommit (no transaction).
    
    # Drop and recreate idx_gr_po CONCURRENTLY
    op.execute("DROP INDEX IF EXISTS idx_gr_po;")
    op.execute(
        "CREATE INDEX CONCURRENTLY idx_gr_po ON goods_receipts(po_id);",
        execution_options={"autocommit": True}
    )
    
    # Drop and recreate idx_gr_received_at CONCURRENTLY
    op.execute("DROP INDEX IF EXISTS idx_gr_received_at;")
    op.execute(
        "CREATE INDEX CONCURRENTLY idx_gr_received_at ON goods_receipts(received_at);",
        execution_options={"autocommit": True}
    )
    
    # Drop and recreate idx_gr_received_by CONCURRENTLY
    op.execute("DROP INDEX IF EXISTS idx_gr_received_by;")
    op.execute(
        "CREATE INDEX CONCURRENTLY idx_gr_received_by ON goods_receipts(received_by);",
        execution_options={"autocommit": True}
    )
    
    # Drop and recreate idx_gr_idempotency CONCURRENTLY
    op.execute("DROP INDEX IF EXISTS idx_gr_idempotency;")
    op.execute(
        "CREATE UNIQUE INDEX CONCURRENTLY idx_gr_idempotency ON goods_receipts(idempotency_key) WHERE idempotency_key IS NOT NULL;",
        execution_options={"autocommit": True}
    )


def downgrade() -> None:
    # Recreate the non-concurrent versions (what the original migration had)
    op.execute("DROP INDEX IF EXISTS idx_gr_idempotency;")
    op.execute("CREATE UNIQUE INDEX idx_gr_idempotency ON goods_receipts(idempotency_key) WHERE idempotency_key IS NOT NULL;")
    
    op.execute("DROP INDEX IF EXISTS idx_gr_received_by;")
    op.execute("CREATE INDEX idx_gr_received_by ON goods_receipts(received_by);")
    
    op.execute("DROP INDEX IF EXISTS idx_gr_received_at;")
    op.execute("CREATE INDEX idx_gr_received_at ON goods_receipts(received_at);")
    
    op.execute("DROP INDEX IF EXISTS idx_gr_po;")
    op.execute("CREATE INDEX idx_gr_po ON goods_receipts(po_id);")