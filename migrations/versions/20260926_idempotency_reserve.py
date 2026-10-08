"""L2 fix: add sp_idempotency_reserve (reserve key before endpoint execution).

Revision ID: 20260926_idempotency_reserve
Revises: 20260926_retention_procedures
Create Date: 2026-09-26
"""
from alembic import op

revision = "20260926_idempotency_reserve"
down_revision = "20260926_retention_procedures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sp_idempotency_reserve(p_key VARCHAR, p_user_id INT)
        RETURNS BOOLEAN AS $$
        DECLARE
            v_inserted INT;
        BEGIN
            INSERT INTO idempotency_keys (key, user_id)
            VALUES (p_key, p_user_id)
            ON CONFLICT (key, user_id) DO NOTHING
            RETURNING id INTO v_inserted;
            RETURN v_inserted IS NOT NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS sp_idempotency_reserve(varchar, integer);")
