"""GAP-016: model_baselines table for pinned per-model baselines.

Revision ID: 20261012_model_baselines
Revises: 20261012_audit_hash_chain
Create Date: 2026-10-12

One pinned baseline per (sku, model_name). MonitoringRepository.baseline_metrics()
reads this table first and falls back to the oldest evaluation window when no
row is pinned (backward compatible). Populated via
POST /ai/monitoring/promote-baseline (write roles only).
"""
from alembic import op
import sqlalchemy as sa

revision = "20261012_model_baselines"
down_revision = "20261012_audit_hash_chain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_baselines",
        sa.Column("id", sa.Integer, primary_key=True),  # SERIAL
        sa.Column("sku", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("mae", sa.Float(), nullable=True),
        sa.Column("mape", sa.Float(), nullable=True),
        sa.Column(
            "source",
            sa.String(),
            nullable=False,
            server_default="promotion",
        ),
        sa.Column("promoted_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("promoted_by", sa.String(), nullable=True),
        sa.UniqueConstraint("sku", "model_name", name="uq_model_baselines_sku_model"),
        sa.CheckConstraint(
            "source IN ('promotion','first_eval')", name="ck_model_baselines_source"
        ),
    )


def downgrade() -> None:
    op.drop_table("model_baselines")
