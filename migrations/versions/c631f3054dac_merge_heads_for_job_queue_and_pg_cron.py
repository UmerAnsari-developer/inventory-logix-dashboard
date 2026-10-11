"""merge heads for job queue and pg_cron

Revision ID: c631f3054dac
Revises: 20260926_idempotency_reserve, 20261008_enable_pg_cron
Create Date: 2026-10-08 13:45:36.773086
"""
from alembic import op
import sqlalchemy as sa


revision = 'c631f3054dac'
down_revision = ('20260926_idempotency_reserve', '20261008_enable_pg_cron')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
