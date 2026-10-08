"""Create scheduled_audit_reports table for audit report generator

Revision ID: 20260920103345
Revises: 20260920101832
Create Date: 2026-09-20T10:33:45.832918
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "20260920103345"
down_revision = "20260920101832"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DB-022: guard against DuplicateTable — 001_initial already creates this table via schema.sql
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table('scheduled_audit_reports'):
        op.create_table(
            'scheduled_audit_reports',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('description', sa.Text),
            sa.Column('format', sa.String(10), nullable=False),  # PDF, CSV
            sa.Column('frequency', sa.String(20), nullable=False),  # daily, weekly, monthly
            sa.Column('parameters', sa.JSON),  # JSON blob for filters, date ranges, etc.
            sa.Column('next_run_time', sa.DateTime),
            sa.Column('last_run_time', sa.DateTime),
            sa.Column('is_active', sa.Boolean, nullable=False, default=True),
            sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('NOW()')),
            sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.text('NOW()')),
            sa.Column('created_by', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
            sa.Column('updated_by', sa.Integer, sa.ForeignKey('users.id'), nullable=False)
        )
        op.create_index('idx_scheduled_audit_reports_next_run', 'scheduled_audit_reports', ['next_run_time'])
        op.create_index('idx_scheduled_audit_reports_active', 'scheduled_audit_reports', ['is_active'])


def downgrade() -> None:
    # DB-066: guard downgrade with IF EXISTS
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table('scheduled_audit_reports'):
        op.drop_index('idx_scheduled_audit_reports_active', table_name='scheduled_audit_reports')
        op.drop_index('idx_scheduled_audit_reports_next_run', table_name='scheduled_audit_reports')
        op.drop_table('scheduled_audit_reports')
