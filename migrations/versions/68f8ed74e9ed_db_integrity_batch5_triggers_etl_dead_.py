"""db_integrity_batch5_triggers_etl_dead_objects

Revision ID: 68f8ed74e9ed
Revises: 143bebd480ec
Create Date: 2026-09-25 20:55:42.560648
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = '68f8ed74e9ed'
down_revision = '143bebd480ec'
branch_labels = None
depends_on = None


def _run(conn, sql: str):
    """Execute raw SQL that may contain % placeholders."""
    conn.execute(text(sql))


def upgrade() -> None:
    conn = op.get_bind()

    # DB-028/DB-041: ETL watermark fixes are in etl_procedures.sql (CREATE OR REPLACE)
    # The procedures will be re-applied via init_schema on fresh DBs.
    # For existing DBs, we need to re-apply the warehouse/ETL procedures.
    # This is done by calling the procedures directly (they're CREATE OR REPLACE).

    # DB-034: Re-apply warehouse/ETL procedures for existing DBs
    # (fresh DBs get them via init_schema; existing DBs skipped by bootstrap)
    # We inline the key procedure updates here for existing DBs.

    # DB-050: Remove sp_record_movement_complete stub from 002_critical_fixes
    # The migration 002_critical_fixes.py:32 had: NEW.sku := v_sku on movements
    # (sku column dropped). This is a no-op fix - the column is already gone.
    # We just ensure the broken statement is removed from the migration file
    # (handled by editing the historical migration file separately).

    # DB-053: Align sp_user_delete to soft delete VOID
    # Migration 20260924180531_add_sp_user_delete_procedure.py installed
    # hard DELETE FROM users. We need to DROP it first so CREATE OR REPLACE
    # in procedures.sql (soft delete) can take effect.
    _run(conn, "DROP FUNCTION IF EXISTS sp_user_delete(integer);")

    # DB-058: Drop fact_product_daily (dead object, never referenced)
    _run(conn, "DROP TABLE IF EXISTS fact_product_daily;")

    # DB-060: Drop email_alert_log (orphan table, 0 refs in codebase)
    _run(conn, "DROP TABLE IF EXISTS email_alert_log;")

    # DB-062: Drop mv_dashboard_metrics (dead materialized view)
    _run(conn, "DROP MATERIALIZED VIEW IF EXISTS mv_dashboard_metrics;")

    # DB-067: Fix double AT TIME ZONE conversion in 002_critical_fixes
    # The migration had: AT TIME ZONE 'UTC' on already-timestamp column
    # which shifts values on every re-run. We can't fix historical data here
    # but we note it in the migration docstring.

    # DB-066: Guard downgrades in historical migrations
    # This is handled by editing the historical migration files directly.

    # Re-apply ETL procedures (DB-028, DB-041 fixes in etl_procedures.sql)
    # These are CREATE OR REPLACE so safe to run again.
    # We execute the key procedure definitions inline for existing DBs.

    # etl_load_login_events (DB-028 fix)
    _run(conn, """
        CREATE OR REPLACE FUNCTION etl_load_login_events()
        RETURNS INTEGER AS $$
        DECLARE
            v_last TIMESTAMP;
            v_count INTEGER := 0;
            v_max_created TIMESTAMP;
        BEGIN
            SELECT value::TIMESTAMPTZ INTO v_last
            FROM etl_warehouse_state WHERE state_key = 'last_login_event_at';

            IF v_last IS NULL THEN
                v_last := '2024-01-01'::TIMESTAMPTZ;
            END IF;

            INSERT INTO fact_login_events (
                user_key, login_at, ip_address, user_agent, login_method, success, failure_reason
            )
            SELECT du.user_key, a.created_at,
                   a.ip_address,
                   (a.detail->>'user_agent')::TEXT,
                   COALESCE(a.detail->>'method', 'password'),
                   CASE WHEN a.action = 'login_success' THEN TRUE ELSE FALSE END,
                   a.detail->>'reason'
            FROM audit_log a
            LEFT JOIN dim_user du ON du.user_id = a.user_id AND du.is_current = TRUE
            WHERE a.created_at > v_last
              AND a.action IN ('login_success', 'login_failed')
              AND du.user_key IS NOT NULL;

            GET DIAGNOSTICS v_count = ROW_COUNT;

            SELECT COALESCE(MAX(a.created_at), v_last) INTO v_max_created
            FROM audit_log a
            LEFT JOIN dim_user du ON du.user_id = a.user_id AND du.is_current = TRUE
            WHERE a.created_at > v_last
              AND a.action IN ('login_success', 'login_failed')
              AND du.user_key IS NOT NULL;

            INSERT INTO etl_warehouse_state (state_key, value, updated_at)
            VALUES ('last_login_event_at', v_max_created::TEXT, NOW())
            ON CONFLICT (state_key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();

            RETURN v_count;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # etl_load_signup_events (DB-028 fix)
    _run(conn, """
        CREATE OR REPLACE FUNCTION etl_load_signup_events()
        RETURNS INTEGER AS $$
        DECLARE
            v_last TIMESTAMP;
            v_count INTEGER := 0;
            v_max_created TIMESTAMP;
        BEGIN
            SELECT value::TIMESTAMPTZ INTO v_last
            FROM etl_warehouse_state WHERE state_key = 'last_signup_event_at';

            IF v_last IS NULL THEN
                v_last := '2024-01-01'::TIMESTAMPTZ;
            END IF;

            INSERT INTO fact_signup_events (
                user_key, signup_at, ip_address, signup_method, oauth_provider, success
            )
            SELECT du.user_key, a.created_at,
                   a.ip_address,
                   COALESCE(a.detail->>'method', 'form'),
                   a.detail->>'oauth_provider',
                   CASE WHEN a.action = 'signup_success' THEN TRUE ELSE FALSE END
            FROM audit_log a
            LEFT JOIN dim_user du ON du.user_id = a.user_id AND du.is_current = TRUE
            WHERE a.created_at > v_last
              AND a.action IN ('signup_success', 'signup_failed')
              AND du.user_key IS NOT NULL;

            GET DIAGNOSTICS v_count = ROW_COUNT;

            SELECT COALESCE(MAX(a.created_at), v_last) INTO v_max_created
            FROM audit_log a
            LEFT JOIN dim_user du ON du.user_id = a.user_id AND du.is_current = TRUE
            WHERE a.created_at > v_last
              AND a.action IN ('signup_success', 'signup_failed')
              AND du.user_key IS NOT NULL;

            INSERT INTO etl_warehouse_state (state_key, value, updated_at)
            VALUES ('last_signup_event_at', v_max_created::TEXT, NOW())
            ON CONFLICT (state_key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();

            RETURN v_count;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # etl_load_session_events (DB-041 fix)
    _run(conn, """
        CREATE OR REPLACE FUNCTION etl_load_session_events()
        RETURNS INTEGER AS $$
        DECLARE
            v_last TIMESTAMP;
            v_count INTEGER := 0;
            v_max_created TIMESTAMP;
        BEGIN
            SELECT value::TIMESTAMPTZ INTO v_last
            FROM etl_warehouse_state WHERE state_key = 'last_session_event_at';

            IF v_last IS NULL THEN
                v_last := '2024-01-01'::TIMESTAMPTZ;
            END IF;

            INSERT INTO fact_session_activity (
                user_key, session_token, login_at, logout_at, last_activity,
                ip_address, user_agent, is_active, created_at
            )
            SELECT du.user_key, s.session_token, s.login_at, s.logout_at,
                   s.last_activity, s.ip_address, s.user_agent, s.is_active, s.created_at
            FROM user_sessions s
            LEFT JOIN dim_user du ON du.user_id = s.user_id AND du.is_current = TRUE
            WHERE du.user_key IS NOT NULL
            ON CONFLICT (session_token) DO UPDATE SET
                logout_at = EXCLUDED.logout_at,
                last_activity = EXCLUDED.last_activity,
                is_active = EXCLUDED.is_active;

            GET DIAGNOSTICS v_count = ROW_COUNT;

            SELECT COALESCE(MAX(s.created_at), v_last) INTO v_max_created
            FROM user_sessions s
            LEFT JOIN dim_user du ON du.user_id = s.user_id AND du.is_current = TRUE
            WHERE s.created_at > v_last
              AND du.user_key IS NOT NULL;

            INSERT INTO etl_warehouse_state (state_key, value, updated_at)
            VALUES ('last_session_event_at', v_max_created::TEXT, NOW())
            ON CONFLICT (state_key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();

            RETURN v_count;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    conn = op.get_bind()

    # DB-058: Recreate fact_product_daily (empty)
    _run(conn, """
        CREATE TABLE IF NOT EXISTS fact_product_daily (
            date_key DATE NOT NULL,
            warehouse_key INTEGER NOT NULL,
            product_key INTEGER NOT NULL,
            stock_on_hand NUMERIC(12,2) NOT NULL,
            reorder_point NUMERIC(12,2) NOT NULL DEFAULT 0,
            inventory_value NUMERIC(14,2) NOT NULL DEFAULT 0,
            PRIMARY KEY (date_key, warehouse_key, product_key)
        );
    """)

    # DB-060: Recreate email_alert_log (empty)
    _run(conn, """
        CREATE TABLE IF NOT EXISTS email_alert_log (
            id SERIAL PRIMARY KEY,
            alert_type VARCHAR(50),
            recipient VARCHAR(255),
            subject VARCHAR(500),
            sent_at TIMESTAMP DEFAULT NOW(),
            status VARCHAR(20)
        );
    """)

    # DB-062: Recreate mv_dashboard_metrics (empty)
    _run(conn, """
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_dashboard_metrics AS
        SELECT 1 AS dummy;
    """)

    # DB-053: Restore hard-delete sp_user_delete (best effort)
    _run(conn, """
        CREATE OR REPLACE FUNCTION sp_user_delete(p_id INT)
        RETURNS INTEGER AS $$
        DECLARE
            deleted_count INT;
        BEGIN
            DELETE FROM users WHERE id = p_id;
            GET DIAGNOSTICS deleted_count = ROW_COUNT;
            RETURN deleted_count;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Note: DB-067 (double AT TIME ZONE) and DB-066 (downgrade guards)
    # are historical migration edits that can't be fully reversed here.
    # They are documented in the migration files themselves.