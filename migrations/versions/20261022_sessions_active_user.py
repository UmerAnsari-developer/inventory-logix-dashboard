"""add composite partial index on user_sessions for active-session lookups.

Matches ``idx_user_sessions_active_user`` in ``app/database/schema.sql`` and
``app/database/optimizations.sql`` so migrated and freshly bootstrapped
databases stay in parity.  Downgrade drops the index; it is safe to re-run.

NOTE: the revision id is 29 chars — Alembic's default
``alembic_version.version_num`` is VARCHAR(32).

Revision ID: 20261022_sessions_active_user
Revises: 20261018_drop_forecast_tables
Create Date: 2026-10-22
"""
from alembic import op

revision = "20261022_sessions_active_user"
down_revision = "20261018_drop_forecast_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Not CONCURRENTLY: Alembic runs inside a transaction.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_sessions_active_user "
        "ON user_sessions (user_id, is_active) WHERE is_active = TRUE;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_user_sessions_active_user;")
