"""DB-044: retention purge procedures for audit/ops tables.

Revision ID: 20260926_retention_procedures
Revises: 20260926_drop_sp_product_update_legacy
Create Date: 2026-09-26
"""
from alembic import op

revision = "20260926_retention_procedures"
down_revision = "20260926_drop_sp_product_update_legacy"
branch_labels = None
depends_on = None

# Same SQL as app/database/procedures.sql (dual-apply rule).
# forecast/anomaly/fact tables intentionally NOT purged — business history.
_UPGRADE = """
CREATE OR REPLACE FUNCTION sp_retention_purge_audit_log(p_days INT DEFAULT 90)
RETURNS INTEGER AS $$
DECLARE
    v_deleted INT;
BEGIN
    DELETE FROM audit_log
    WHERE created_at < NOW() - (p_days || ' days')::interval;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_retention_purge_user_sessions(p_days INT DEFAULT 90)
RETURNS INTEGER AS $$
DECLARE
    v_deleted INT;
BEGIN
    DELETE FROM user_sessions
    WHERE is_active = FALSE
      AND last_activity < NOW() - (p_days || ' days')::interval;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_retention_purge_idempotency_keys(p_days INT DEFAULT 30)
RETURNS INTEGER AS $$
DECLARE
    v_deleted INT;
BEGIN
    DELETE FROM idempotency_keys
    WHERE created_at < NOW() - (p_days || ' days')::interval;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_retention_purge_rate_limit_state()
RETURNS INTEGER AS $$
DECLARE
    v_deleted INT;
BEGIN
    DELETE FROM rate_limit_state
    WHERE expires_at < NOW();
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_retention_run_all()
RETURNS TABLE(object_name TEXT, purged INTEGER) AS $$
BEGIN
    object_name := 'audit_log';
    purged := sp_retention_purge_audit_log();
    RETURN NEXT;
    object_name := 'user_sessions';
    purged := sp_retention_purge_user_sessions();
    RETURN NEXT;
    object_name := 'idempotency_keys';
    purged := sp_retention_purge_idempotency_keys();
    RETURN NEXT;
    object_name := 'rate_limit_state';
    purged := sp_retention_purge_rate_limit_state();
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    # Drop run_all first (calls the others), then each purge by full signature.
    op.execute("DROP FUNCTION IF EXISTS sp_retention_run_all();")
    op.execute("DROP FUNCTION IF EXISTS sp_retention_purge_rate_limit_state();")
    op.execute("DROP FUNCTION IF EXISTS sp_retention_purge_idempotency_keys(integer);")
    op.execute("DROP FUNCTION IF EXISTS sp_retention_purge_user_sessions(integer);")
    op.execute("DROP FUNCTION IF EXISTS sp_retention_purge_audit_log(integer);")
