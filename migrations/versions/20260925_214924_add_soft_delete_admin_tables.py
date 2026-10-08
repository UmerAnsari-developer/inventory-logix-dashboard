"""Add soft delete columns to admin tables

Revision ID: 20260925_214924
Revises: 20260925_db_integrity_fixes
Create Date: 2026-09-25 21:49:24.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260925_214924'
down_revision = '20260925_db_integrity_fixes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add deleted_at column to system_backups
    op.add_column('system_backups', sa.Column('deleted_at', sa.TIMESTAMP(), nullable=True))
    op.add_column('system_backups', sa.Column('encrypted', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('system_backups', sa.Column('encryption_key_id', sa.String(100), nullable=True))
    op.add_column('system_backups', sa.Column('checksum', sa.String(64), nullable=True))
    op.create_index('idx_system_backups_deleted_at', 'system_backups', ['deleted_at'], 
                    postgresql_where=sa.text('deleted_at IS NULL'))
    
    # Add deleted_at column to system_config_overrides
    op.add_column('system_config_overrides', sa.Column('deleted_at', sa.TIMESTAMP(), nullable=True))
    op.create_index('idx_system_config_overrides_deleted_at', 'system_config_overrides', ['deleted_at'],
                    postgresql_where=sa.text('deleted_at IS NULL'))
    
    # Add deleted_at column to scheduled_audit_reports
    op.add_column('scheduled_audit_reports', sa.Column('deleted_at', sa.TIMESTAMP(), nullable=True))
    op.create_index('idx_scheduled_audit_reports_deleted_at', 'scheduled_audit_reports', ['deleted_at'],
                    postgresql_where=sa.text('deleted_at IS NULL'))


def downgrade() -> None:
    # Remove indexes
    op.drop_index('idx_scheduled_audit_reports_deleted_at', table_name='scheduled_audit_reports')
    op.drop_index('idx_system_config_overrides_deleted_at', table_name='system_config_overrides')
    op.drop_index('idx_system_backups_deleted_at', table_name='system_backups')
    
    # Remove columns
    op.drop_column('scheduled_audit_reports', 'deleted_at')
    op.drop_column('system_config_overrides', 'deleted_at')
    op.drop_column('system_backups', 'checksum')
    op.drop_column('system_backups', 'encryption_key_id')
    op.drop_column('system_backups', 'encrypted')
    op.drop_column('system_backups', 'deleted_at')