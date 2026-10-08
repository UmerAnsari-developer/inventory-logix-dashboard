"""add sp_record_movement_complete procedure

REPAIRED: the original body was invalid SQL (procedure declared without
LANGUAGE ... AS $$, references to a non-existent products.product_id column,
sp_movement_record called with a non-existent signature, PERFORM inside a
procedure) and could never execute. No application code CALLs this procedure
(procedures.sql only keeps a zero-argument stub FUNCTION of the same name), so
the revision now applies a harmless no-op that keeps the up/down chain valid.

Revision ID: 20260924191107
Revises: 20260924180531
Create Date: 2026-09-24T19:11:07.388484
"""
from alembic import op
import sqlalchemy as sa

revision = "20260924191107"
down_revision = "20260924180531"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op: drop the (never valid) procedure if a previous partial run left it.
    op.get_bind().exec_driver_sql(
        "DROP PROCEDURE IF EXISTS sp_record_movement_complete("
        "INTEGER, VARCHAR, INTEGER, VARCHAR, INTEGER, TEXT);"
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "DROP PROCEDURE IF EXISTS sp_record_movement_complete("
        "INTEGER, VARCHAR, INTEGER, VARCHAR, INTEGER, TEXT);"
    )
