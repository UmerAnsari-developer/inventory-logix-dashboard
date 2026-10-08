"""merge heads

Revision ID: 2a13749777f1
Revises: 20260925_214924, 68f8ed74e9ed
Create Date: 2026-09-25 22:11:56.326986
"""
from alembic import op
import sqlalchemy as sa


revision = '2a13749777f1'
down_revision = ('20260925_214924', '68f8ed74e9ed')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
