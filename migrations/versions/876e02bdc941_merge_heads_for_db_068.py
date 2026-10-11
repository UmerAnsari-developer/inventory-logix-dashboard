"""merge heads for DB-068

Revision ID: 876e02bdc941
Revises: 20260926_guc, d548499a4a0d
Create Date: 2026-09-26 12:43:28.346086
"""
from alembic import op
import sqlalchemy as sa


revision = '876e02bdc941'
down_revision = ('20260926_guc', 'd548499a4a0d')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
