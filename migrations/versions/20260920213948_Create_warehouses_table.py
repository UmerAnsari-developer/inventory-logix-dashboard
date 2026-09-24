"""Create warehouses table

Revision ID: 20260920213948
Revises: 20260920103345
Create Date: 2026-09-20T21:39:48.467012
"""
from alembic import op
import sqlalchemy as sa

revision = "20260920213948"
down_revision = "20260920103345"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS: schema.sql may have created the table on the
    # bootstrap path before alembic runs (fresh installs).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS warehouses (
            id SERIAL PRIMARY KEY,
            warehouse_name VARCHAR(120) NOT NULL,
            location VARCHAR(200),
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )


def downgrade() -> None:
    op.drop_table('warehouses')