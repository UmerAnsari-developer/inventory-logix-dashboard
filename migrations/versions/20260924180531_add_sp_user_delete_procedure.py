"""add sp_user_delete procedure

Revision ID: 20260924180531
Revises: optimizations_20260922
Create Date: 2026-09-24T18:05:31.443989
"""
from alembic import op
import sqlalchemy as sa

revision = "20260924180531"
down_revision = "optimizations_20260922"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DB-053: soft delete (UPDATE deleted_at) not hard DELETE
    # Return type VOID to match procedures.sql
    op.execute("""CREATE OR REPLACE FUNCTION sp_user_delete(p_user_id INTEGER) RETURNS VOID LANGUAGE plpgsql AS $$ BEGIN UPDATE users SET deleted_at = NOW() WHERE id = p_user_id; END; $$;""")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS sp_user_delete(INTEGER);")
