-- =============================================================================
-- InventoryLogix — ETL Stored Procedures (Warehouse Layer)
-- Incremental loading, SCD Type 2 merges, event processing
-- =============================================================================

-- ── SCD TYPE 2: MERGE PRODUCT ───────────────────────────────────────────────
-- Compares current operational data with SCD table, inserts new rows for changes

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


-- ── SCD TYPE 2: MERGE SUPPLIERS ─────────────────────────────────────────────

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


-- ── SCD TYPE 2: MERGE WAREHOUSES ────────────────────────────────────────────

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


-- ── SCD TYPE 2: MERGE USERS ─────────────────────────────────────────────────

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


-- ── INCREMENTAL: PROCESS LOGIN EVENTS ───────────────────────────────────────
-- Reads from audit_log where action = 'login.*' and inserts into fact_login_events

CREATE OR REPLACE FUNCTION etl_load_login_events()
RETURNS INTEGER AS $$
DECLARE
    v_last TIMESTAMP;
    v_count INTEGER := 0;
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

    INSERT INTO etl_warehouse_state (state_key, value, updated_at)
    VALUES ('last_login_event_at', NOW()::TEXT, NOW())
    ON CONFLICT (state_key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- ── INCREMENTAL: PROCESS SESSION EVENTS ──────────────────────────────────────
-- Syncs user_sessions into fact_session_activity

CREATE OR REPLACE FUNCTION etl_load_session_events()
RETURNS INTEGER AS $$
DECLARE
    v_last TIMESTAMP;
    v_count INTEGER := 0;
BEGIN
    SELECT value::TIMESTAMPTZ INTO v_last
    FROM etl_warehouse_state WHERE state_key = 'last_session_event_at';

    IF v_last IS NULL THEN
        v_last := '2024-01-01'::TIMESTAMPTZ;
    END IF;

    -- Upsert new/changed sessions
    INSERT INTO fact_session_activity (
        user_key, session_token, login_at, logout_at, last_activity,
        ip_address, user_agent, is_active, created_at
    )
    SELECT du.user_key, s.session_token, s.login_at, s.logout_at,
           s.last_activity, s.ip_address, s.user_agent, s.is_active, s.created_at
    FROM user_sessions s
    LEFT JOIN dim_user du ON du.user_id = s.user_id AND du.is_current = TRUE
    WHERE s.created_at > v_last
      AND du.user_key IS NOT NULL
    ON CONFLICT (session_token) DO UPDATE SET
        logout_at = EXCLUDED.logout_at,
        last_activity = EXCLUDED.last_activity,
        is_active = EXCLUDED.is_active;

    GET DIAGNOSTICS v_count = ROW_COUNT;

    INSERT INTO etl_warehouse_state (state_key, value, updated_at)
    VALUES ('last_session_event_at', NOW()::TEXT, NOW())
    ON CONFLICT (state_key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- ── INCREMENTAL: PROCESS SIGNUP EVENTS ──────────────────────────────────────

CREATE OR REPLACE FUNCTION etl_load_signup_events()
RETURNS INTEGER AS $$
DECLARE
    v_last TIMESTAMP;
    v_count INTEGER := 0;
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

    INSERT INTO etl_warehouse_state (state_key, value, updated_at)
    VALUES ('last_signup_event_at', NOW()::TEXT, NOW())
    ON CONFLICT (state_key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- ── INCREMENTAL: PROCESS AUDIT DAILY ────────────────────────────────────────
-- Aggregates audit_log into fact_audit_daily

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

    -- Delete existing rows for days we're reprocessing
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


-- ── FULL WAREHOUSE BUILD ────────────────────────────────────────────────────
-- Runs all ETL steps in sequence. Called on startup or manually.

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


-- ── MONITORING QUERIES (Stored Procedures) ───────────────────────────────────

CREATE OR REPLACE FUNCTION sp_monitor_active_sessions()
RETURNS TABLE (
    username VARCHAR,
    login_at TIMESTAMP,
    last_activity TIMESTAMP,
    duration_min INTEGER,
    ip_address VARCHAR,
    is_active BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT du.username, fs.login_at, fs.last_activity,
           CASE WHEN fs.logout_at IS NOT NULL
                THEN EXTRACT(EPOCH FROM (fs.logout_at - fs.login_at))::INTEGER / 60
                ELSE EXTRACT(EPOCH FROM (NOW() - fs.login_at))::INTEGER / 60
           END AS duration_min,
           fs.ip_address, fs.is_active
    FROM fact_session_activity fs
    JOIN dim_user du ON du.user_key = fs.user_key AND du.is_current = TRUE
    ORDER BY fs.last_activity DESC;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_monitor_login_history(p_limit INT DEFAULT 20)
RETURNS TABLE (
    username VARCHAR,
    login_at TIMESTAMP,
    ip_address VARCHAR,
    login_method VARCHAR,
    success BOOLEAN,
    failure_reason VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT du.username, fl.login_at, fl.ip_address,
           fl.login_method, fl.success, fl.failure_reason
    FROM fact_login_events fl
    JOIN dim_user du ON du.user_key = fl.user_key AND du.is_current = TRUE
    ORDER BY fl.login_at DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_monitor_signup_history(p_limit INT DEFAULT 20)
RETURNS TABLE (
    username VARCHAR,
    signup_at TIMESTAMP,
    signup_method VARCHAR,
    oauth_provider VARCHAR,
    success BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT du.username, fs.signup_at, fs.signup_method,
           fs.oauth_provider, fs.success
    FROM fact_signup_events fs
    JOIN dim_user du ON du.user_key = fs.user_key AND du.is_current = TRUE
    ORDER BY fs.signup_at DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_monitor_user_activity_summary()
RETURNS TABLE (
    username VARCHAR,
    role VARCHAR,
    total_logins BIGINT,
    total_sessions BIGINT,
    last_login TIMESTAMP,
    avg_session_min NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT du.username, du.role,
           COUNT(DISTINCT fl.event_id) AS total_logins,
           COUNT(DISTINCT fs.session_key) AS total_sessions,
           MAX(fl.login_at) AS last_login,
           ROUND(AVG(
               CASE WHEN fs.logout_at IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (fs.logout_at - fs.login_at)) / 60.0
                    ELSE NULL END
           ), 1) AS avg_session_min
    FROM dim_user du
    LEFT JOIN fact_login_events fl ON fl.user_key = du.user_key
    LEFT JOIN fact_session_activity fs ON fs.user_key = du.user_key
    WHERE du.is_current = TRUE
    GROUP BY du.user_key, du.username, du.role
    ORDER BY last_login DESC NULLS LAST;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_monitor_daily_logins(p_days INT DEFAULT 30)
RETURNS TABLE (
    day DATE,
    total_logins BIGINT,
    successful_logins BIGINT,
    failed_logins BIGINT,
    unique_users BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT fl.login_at::DATE AS day,
           COUNT(*)::BIGINT AS total_logins,
           COUNT(*) FILTER (WHERE fl.success = TRUE)::BIGINT AS successful_logins,
           COUNT(*) FILTER (WHERE fl.success = FALSE)::BIGINT AS failed_logins,
           COUNT(DISTINCT fl.user_key)::BIGINT AS unique_users
    FROM fact_login_events fl
    WHERE fl.login_at >= CURRENT_DATE - p_days
    GROUP BY fl.login_at::DATE
    ORDER BY day;
END;
$$ LANGUAGE plpgsql;
