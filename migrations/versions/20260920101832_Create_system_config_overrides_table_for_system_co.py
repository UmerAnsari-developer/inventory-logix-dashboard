"""Create system_config_overrides table for system configuration override

Revision ID: 20260920101832
Revises:
Create Date: 2026-09-20T10:18:32.945221
"""
from alembic import op
import sqlalchemy as sa

revision = "20260920101832"
down_revision = "20260920101012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'system_config_overrides',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('key', sa.String(80), nullable=False, unique=True),
        sa.Column('value', sa.Text),
        sa.Column('description', sa.Text),
        sa.Column('updated_at', sa.TIMESTAMP, nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_by', sa.Integer, sa.ForeignKey('users.id'), nullable=False)
    )
    op.create_index('idx_system_config_overrides_key', 'system_config_overrides', ['key'])
    op.create_index('idx_system_config_overrides_updated_at', 'system_config_overrides', ['updated_at'])


def downgrade() -> None:
    op.drop_index('idx_system_config_overrides_updated_at', table_name='system_config_overrides')
    op.drop_index('idx_system_config_overrides_key', table_name='system_config_overrides')
    op.drop_table('system_config_overrides')
