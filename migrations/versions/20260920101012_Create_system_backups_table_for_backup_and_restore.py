"""Create system_backups table for backup and restore feature

Revision ID: 20260920101012
Revises:
Create Date: 2026-09-20T10:10:12.715197
"""
from alembic import op
import sqlalchemy as sa

revision = "20260920101012"
down_revision = "003_enable_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'system_backups',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('backup_name', sa.String(255), nullable=False),
        sa.Column('backup_type', sa.String(50), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('size', sa.BigInteger),
        sa.Column('status', sa.String(50), nullable=False, default='success'),
        sa.Column('created_at', sa.TIMESTAMP, nullable=False, server_default=sa.text('NOW()')),
        sa.Column('created_by', sa.Integer, sa.ForeignKey('users.id'), nullable=False)
    )
    op.create_index('idx_system_backups_created_at', 'system_backups', ['created_at'])
    op.create_index('idx_system_backups_created_by', 'system_backups', ['created_by'])


def downgrade() -> None:
    op.drop_index('idx_system_backups_created_by', table_name='system_backups')
    op.drop_index('idx_system_backups_created_at', table_name='system_backups')
    op.drop_table('system_backups')
