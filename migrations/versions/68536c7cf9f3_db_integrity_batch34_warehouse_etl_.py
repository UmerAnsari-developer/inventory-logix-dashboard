"""db_integrity_batch34_warehouse_etl_reapply

Revision ID: 68536c7cf9f3
Revises: 2a13749777f1
Create Date: 2026-09-25 22:57:14.102092
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = '68536c7cf9f3'
down_revision = '2a13749777f1'
branch_labels = None
depends_on = None


def _run(conn, sql: str):
    """Execute raw SQL that may contain % placeholders."""
    conn.execute(text(sql))


def upgrade() -> None:
    conn = op.get_bind()

    # DB-034: Re-apply warehouse/ETL procedures for existing DBs
    # (fresh DBs get them via init_schema; existing DBs skipped by bootstrap)
    # We inline the key procedure definitions here for existing DBs.

    # ── SCD TYPE 2: MERGE PRODUCTS ───────────────────────────────────────────────
    _run(conn, """
        CREATE OR REPLACE FUNCTION etl_scd_merge_products()
        RETURNS INTEGER AS $$
        DECLARE
            v_total INTEGER := 0;
            v_temp  INTEGER;
        BEGIN
            -- Close records that changed
            UPDATE dim_product_scd scd
            SET valid_to = NOW(), is_current = FALSE
            FROM products p
            WHERE scd.sku = p.sku
              AND scd.is_current = TRUE
              AND (
                  scd.product_name != p.name
                  OR scd.category IS DISTINCT FROM p.category
                  OR scd.warehouse IS DISTINCT FROM p.warehouse
                  OR scd.unit_price IS DISTINCT FROM p.unit_price
                  OR scd.current_stock != p.current_stock
                  OR scd.reorder_point != p.reorder_point
                  OR scd.supplier_id IS DISTINCT FROM p.supplier_id
              );

            GET DIAGNOSTICS v_temp = ROW_COUNT;
            v_total := v_total + v_temp;

            -- Insert new current records for changed + new products
            INSERT INTO dim_product_scd (
                sku, product_name, category, warehouse, supplier_id,
                unit_price, current_stock, reorder_point, valid_from, is_current, row_hash
            )
            SELECT p.sku, p.name, p.category, p.warehouse, p.supplier_id,
                   p.unit_price, p.current_stock, p.reorder_point, NOW(), TRUE,
                   MD5(ROW(p.sku, p.name, p.category, p.warehouse, p.supplier_id,
                           p.unit_price, p.current_stock, p.reorder_point)::TEXT)
            FROM products p
            WHERE NOT EXISTS (
                SELECT 1 FROM dim_product_scd scd
                WHERE scd.sku = p.sku AND scd.is_current = TRUE
            );

            GET DIAGNOSTICS v_temp = ROW_COUNT;
            v_total := v_total + v_temp;
            RETURN v_total;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # ── SCD TYPE 2: MERGE SUPPLIERS ─────────────────────────────────────────────
    _run(conn, """
        CREATE OR REPLACE FUNCTION etl_scd_merge_suppliers()
        RETURNS INTEGER AS $$
        DECLARE
            v_total INTEGER := 0;
            v_temp  INTEGER;
        BEGIN
            -- Close changed records
            UPDATE dim_supplier_scd scd
            SET valid_to = NOW(), is_current = FALSE
            FROM suppliers s
            WHERE scd.supplier_id = s.id
              AND scd.is_current = TRUE
              AND (
                  scd.supplier_name != s.name
                  OR scd.location IS DISTINCT FROM s.location
                  OR scd.reliability IS DISTINCT FROM s.reliability
                  OR scd.lead_days != s.lead_days
                  OR scd.spend_amount IS DISTINCT FROM s.spend_amount
              );

            GET DIAGNOSTICS v_temp = ROW_COUNT;
            v_total := v_total + v_temp;

            -- Insert new records
            INSERT INTO dim_supplier_scd (
                supplier_id, supplier_name, location, reliability, lead_days,
                spend_amount, valid_from, is_current, row_hash
            )
            SELECT s.id, s.name, s.location, s.reliability, s.lead_days,
                   s.spend_amount, NOW(), TRUE,
                   MD5(ROW(s.id, s.name, s.location, s.reliability, s.lead_days, s.spend_amount)::TEXT)
            FROM suppliers s
            WHERE NOT EXISTS (
                SELECT 1 FROM dim_supplier_scd scd
                WHERE scd.supplier_id = s.id AND scd.is_current = TRUE
            );

            GET DIAGNOSTICS v_temp = ROW_COUNT;
            v_total := v_total + v_temp;
            RETURN v_total;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # ── SCD TYPE 2: MERGE WAREHOUSES ────────────────────────────────────────────
    _run(conn, """
        CREATE OR REPLACE FUNCTION etl_scd_merge_warehouses()
        RETURNS INTEGER AS $$
        DECLARE
            v_total INTEGER := 0;
            v_temp  INTEGER;
        BEGIN
            -- Close changed records
            UPDATE dim_warehouse_scd scd
            SET valid_to = NOW(), is_current = FALSE
            FROM (
                SELECT DISTINCT warehouse, warehouse AS warehouse_name
                FROM products WHERE warehouse IS NOT NULL
            ) w
            WHERE scd.warehouse_name = w.warehouse_name
              AND scd.is_current = TRUE;

            GET DIAGNOSTICS v_temp = ROW_COUNT;
            v_total := v_total + v_temp;

            -- Insert new warehouse records
            INSERT INTO dim_warehouse_scd (
                warehouse_code, warehouse_name, city, region,
                valid_from, is_current, row_hash
            )
            SELECT
                SUBSTRING(w.warehouse FROM 4 FOR 3),
                w.warehouse,
                SUBSTRING(w.warehouse FROM 4),
                CASE
                    WHEN w.warehouse ILIKE '%Pune%' THEN 'Central'
                    WHEN w.warehouse ILIKE '%Mumbai%' THEN 'West'
                    WHEN w.warehouse ILIKE '%Delhi%' THEN 'North'
                    WHEN w.warehouse ILIKE '%Bengaluru%' THEN 'South'
                    WHEN w.warehouse ILIKE '%Chennai%' THEN 'South'
                    ELSE 'General'
                END,
                NOW(), TRUE,
                MD5(w.warehouse)
            FROM (
                SELECT DISTINCT warehouse FROM products WHERE warehouse IS NOT NULL
            ) w
            WHERE NOT EXISTS (
                SELECT 1 FROM dim_warehouse_scd scd
                WHERE scd.warehouse_name = w.warehouse AND scd.is_current = TRUE
            );

            GET DIAGNOSTICS v_temp = ROW_COUNT;
            v_total := v_total + v_temp;
            RETURN v_total;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # ── SCD TYPE 2: MERGE USERS ─────────────────────────────────────────────────
    _run(conn, """
        CREATE OR REPLACE FUNCTION etl_scd_merge_users()
        RETURNS INTEGER AS $$
        DECLARE
            v_total INTEGER := 0;
            v_temp  INTEGER;
        BEGIN
            -- Close changed records
            UPDATE dim_user scd
            SET valid_to = NOW(), is_current = FALSE
            FROM users u
            WHERE scd.user_id = u.id
              AND scd.is_current = TRUE
              AND (
                  scd.username != u.username
                  OR scd.email IS DISTINCT FROM u.email
                  OR scd.role != u.role
                  OR scd.is_active != u.is_active
                  OR scd.oauth_provider IS DISTINCT FROM u.oauth_provider
              );

            GET DIAGNOSTICS v_temp = ROW_COUNT;
            v_total := v_total + v_temp;

            -- Insert new records
            INSERT INTO dim_user (
                user_id, username, email, role, oauth_provider,
                is_active, valid_from, is_current, row_hash
            )
            SELECT u.id, u.username, u.email, u.role, u.oauth_provider,
                   u.is_active, NOW(), TRUE,
                   MD5(ROW(u.id, u.username, u.email, u.role, u.oauth_provider, u.is_active)::TEXT)
            FROM users u
            WHERE NOT EXISTS (
                SELECT 1 FROM dim_user scd
                WHERE scd.user_id = u.id AND scd.is_current = TRUE
            );

            GET DIAGNOSTICS v_temp = ROW_COUNT;
            v_total := v_total + v_temp;
            RETURN v_total;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # ── INCREMENTAL: PROCESS LOGIN EVENTS ───────────────────────────────────────
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

    # ── INCREMENTAL: PROCESS SESSION EVENTS ──────────────────────────────────────
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

    # ── INCREMENTAL: PROCESS SIGNUP EVENTS ──────────────────────────────────────
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

    # ── INCREMENTAL: PROCESS AUDIT DAILY ────────────────────────────────────────
    _run(conn, """
        CREATE OR REPLACE FUNCTION etl_load_audit_daily()
        RETURNS INTEGER AS $$
        DECLARE
            v_last DATE;
            v_count INTEGER := 0;
        BEGIN
            SELECT value::DATE INTO v_last
            FROM etl_warehouse_state WHERE state_key = 'last_audit_daily_at';

            IF v_last IS NULL THEN
                v_last := '2024-01-01'::DATE;
            END IF;

            DELETE FROM fact_audit_daily WHERE date_key >= v_last;

            INSERT INTO fact_audit_daily (date_key, action, target_type, user_key, event_count)
            SELECT a.created_at::DATE,
                   a.action,
                   a.target_type,
                   du.user_key,
                   COUNT(*)::INTEGER
            FROM audit_log a
            LEFT JOIN dim_user du ON du.user_id = a.user_id AND du.is_current = TRUE
            WHERE a.created_at::DATE >= v_last
              AND du.user_key IS NOT NULL
            GROUP BY a.created_at::DATE, a.action, a.target_type, du.user_key;

            GET DIAGNOSTICS v_count = ROW_COUNT;

            INSERT INTO etl_warehouse_state (state_key, value, updated_at)
            VALUES ('last_audit_daily_at', CURRENT_DATE::TEXT, NOW())
            ON CONFLICT (state_key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();

            RETURN v_count;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # ── FULL WAREHOUSE BUILD ────────────────────────────────────────────────────
    _run(conn, """
        CREATE OR REPLACE FUNCTION etl_full_build()
        RETURNS TABLE (
            step_name TEXT,
            rows_affected INTEGER
        ) AS $$
        DECLARE
            v_result INTEGER;
        BEGIN
            -- Ensure dim_date covers the full range needed
            -- Build from 2024-01-01 through today + 1 year
            INSERT INTO dim_date (date_key, year, quarter, month, month_name,
                                  day_of_month, day_of_week, week, is_weekend)
            SELECT d::DATE, EXTRACT(YEAR FROM d)::SMALLINT,
                   EXTRACT(QUARTER FROM d)::SMALLINT,
                   EXTRACT(MONTH FROM d)::SMALLINT,
                   TO_CHAR(d, 'Mon'),
                   EXTRACT(DAY FROM d)::SMALLINT,
                   EXTRACT(ISODOW FROM d)::SMALLINT,
                   EXTRACT(WEEK FROM d)::SMALLINT,
                   (EXTRACT(ISODOW FROM d) IN (6,7))
            FROM generate_series('2024-01-01'::DATE, CURRENT_DATE + INTERVAL '1 year', '1 day'::INTERVAL) d
            ON CONFLICT (date_key) DO NOTHING;

            -- SCD merges
            SELECT etl_scd_merge_products() INTO v_result;
            step_name := 'scd_products';
            rows_affected := v_result;
            RETURN NEXT;

            SELECT etl_scd_merge_suppliers() INTO v_result;
            step_name := 'scd_suppliers';
            rows_affected := v_result;
            RETURN NEXT;

            SELECT etl_scd_merge_warehouses() INTO v_result;
            step_name := 'scd_warehouses';
            rows_affected := v_result;
            RETURN NEXT;

            SELECT etl_scd_merge_users() INTO v_result;
            step_name := 'scd_users';
            rows_affected := v_result;
            RETURN NEXT;

            -- Event fact loads
            SELECT etl_load_login_events() INTO v_result;
            step_name := 'login_events';
            rows_affected := v_result;
            RETURN NEXT;

            SELECT etl_load_session_events() INTO v_result;
            step_name := 'session_events';
            rows_affected := v_result;
            RETURN NEXT;

            SELECT etl_load_signup_events() INTO v_result;
            step_name := 'signup_events';
            rows_affected := v_result;
            RETURN NEXT;

            SELECT etl_load_audit_daily() INTO v_result;
            step_name := 'audit_daily';
            rows_affected := v_result;
            RETURN NEXT;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    conn = op.get_bind()

    # Drop the re-applied procedures
    _run(conn, """
        DROP FUNCTION IF EXISTS etl_scd_merge_products();
        DROP FUNCTION IF EXISTS etl_scd_merge_suppliers();
        DROP FUNCTION IF EXISTS etl_scd_merge_warehouses();
        DROP FUNCTION IF EXISTS etl_scd_merge_users();
        DROP FUNCTION IF EXISTS etl_load_login_events();
        DROP FUNCTION IF EXISTS etl_load_session_events();
        DROP FUNCTION IF EXISTS etl_load_signup_events();
        DROP FUNCTION IF EXISTS etl_load_audit_daily();
        DROP FUNCTION IF EXISTS etl_full_build();
    """)