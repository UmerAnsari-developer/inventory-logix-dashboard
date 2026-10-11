"""Create job_queue table for persistent job queue (GAP-012).

Revision ID: 20261008_create_job_queue_table
Revises: 68f8ed74e9ed
Create Date: 2026-10-08
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20261008_create_job_queue_table"
down_revision = "68f8ed74e9ed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create job_queue table
    op.create_table(
        "job_queue",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("task_name", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_run", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id", name="job_queue_pkey"),
    )

    # Partial index for efficient dequeue (FOR UPDATE SKIP LOCKED)
    op.create_index(
        "idx_job_queue_dequeue",
        "job_queue",
        ["status", "next_run", "priority", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # Index for status lookups
    op.create_index("idx_job_queue_status", "job_queue", ["status"])


def downgrade() -> None:
    op.drop_index("idx_job_queue_status", table_name="job_queue")
    op.drop_index("idx_job_queue_dequeue", table_name="job_queue")
    op.drop_table("job_queue")