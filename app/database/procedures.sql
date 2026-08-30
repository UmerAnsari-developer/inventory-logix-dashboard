-- =============================================================================
-- InventoryLogix — Stored Procedures for CRUD operations
-- All application queries go through these procedures to prevent SQL injection
-- =============================================================================

-- ── PRODUCTS ─────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION sp_product_list(
    p_search   TEXT DEFAULT '',
    p_category TEXT DEFAULT '',
    p_warehouse TEXT DEFAULT '',
    p_status   TEXT DEFAULT '',
    p_limit    INT DEFAULT 100,
    p_offset   INT DEFAULT 0
) RETURNS TABLE (
    id INT, sku VARCHAR, name VARCHAR, category VARCHAR, warehouse VARCHAR,
    current_stock INT, reorder_point INT, demand_rate NUMERIC,
    ordering_cost NUMERIC, holding_cost NUMERIC, unit_price NUMERIC,
    supplier_id INT, on_order INT, created_at TIMESTAMP, updated_at TIMESTAMP,
    supplier_name VARCHAR, supplier_tone VARCHAR, lead_days INT,
    total_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    WITH filtered AS (
        SELECT p.*, s.name AS supplier_name, s.tone AS supplier_tone, s.lead_days
        FROM products p
        LEFT JOIN suppliers s ON s.id = p.supplier_id
        WHERE (p_search = '' OR p.sku ILIKE '%' || p_search || '%'
                            OR p.name ILIKE '%' || p_search || '%'
                            OR p.category ILIKE '%' || p_search || '%'
                            OR s.name ILIKE '%' || p_search || '%')
          AND (p_category = '' OR p.category = p_category)
          AND (p_warehouse = '' OR p.warehouse = p_warehouse)
          AND (p_status = '' OR
               (p_status = 'ok' AND p.current_stock > p.reorder_point) OR
               (p_status = 'low' AND p.current_stock <= p.reorder_point AND p.current_stock > 0) OR
               (p_status = 'out' AND p.current_stock <= 0))
    )
    SELECT f.*, (SELECT COUNT(*) FROM filtered) AS total_count
    FROM filtered f
    ORDER BY f.sku
    LIMIT p_limit OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_product_find(p_id INT)
RETURNS SETOF products AS $$
BEGIN
    RETURN QUERY SELECT * FROM products WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_product_find_by_sku(p_sku VARCHAR)
RETURNS SETOF products AS $$
BEGIN
    RETURN QUERY SELECT * FROM products WHERE sku = p_sku;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_product_create(
    p_sku VARCHAR, p_name VARCHAR, p_category VARCHAR DEFAULT '',
    p_warehouse VARCHAR DEFAULT 'WH-Pune', p_current_stock INT DEFAULT 0,
    p_reorder_point INT DEFAULT 0, p_demand_rate NUMERIC DEFAULT 0,
    p_ordering_cost NUMERIC DEFAULT 0, p_holding_cost NUMERIC DEFAULT 0,
    p_unit_price NUMERIC DEFAULT 0, p_supplier_id INT DEFAULT NULL
) RETURNS INT AS $$
DECLARE
    new_id INT;
BEGIN
    INSERT INTO products (sku, name, category, warehouse, current_stock, reorder_point,
                          demand_rate, ordering_cost, holding_cost, unit_price, supplier_id)
    VALUES (p_sku, p_name, p_category, p_warehouse, p_current_stock, p_reorder_point,
            p_demand_rate, p_ordering_cost, p_holding_cost, p_unit_price, p_supplier_id)
    RETURNING id INTO new_id;
    RETURN new_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_product_update(
    p_id INT, p_name VARCHAR, p_category VARCHAR DEFAULT '',
    p_warehouse VARCHAR DEFAULT 'WH-Pune', p_unit_price NUMERIC DEFAULT 0,
    p_supplier_id INT DEFAULT NULL, p_current_stock INT DEFAULT 0,
    p_reorder_point INT DEFAULT 0, p_demand_rate NUMERIC DEFAULT 0,
    p_ordering_cost NUMERIC DEFAULT 0, p_holding_cost NUMERIC DEFAULT 0
) RETURNS VOID AS $$
BEGIN
    UPDATE products SET
        name = p_name, category = p_category, warehouse = p_warehouse,
        unit_price = p_unit_price, supplier_id = p_supplier_id,
        current_stock = p_current_stock, reorder_point = p_reorder_point,
        demand_rate = p_demand_rate, ordering_cost = p_ordering_cost,
        holding_cost = p_holding_cost, updated_at = NOW()
    WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_product_delete(p_id INT)
RETURNS VOID AS $$
BEGIN
    DELETE FROM products WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_product_set_stock(p_id INT, p_value INT)
RETURNS VOID AS $$
BEGIN
    UPDATE products SET current_stock = p_value, updated_at = NOW() WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_product_set_on_order(p_id INT, p_qty INT)
RETURNS VOID AS $$
BEGIN
    UPDATE products SET on_order = p_qty, updated_at = NOW() WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_product_categories()
RETURNS TABLE(category VARCHAR) AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT p.category FROM products p
    WHERE p.category IS NOT NULL ORDER BY p.category;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_product_warehouses()
RETURNS TABLE(warehouse VARCHAR) AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT p.warehouse FROM products p
    WHERE p.warehouse IS NOT NULL ORDER BY p.warehouse;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_product_low_stock()
RETURNS TABLE (
    id INT, sku VARCHAR, name VARCHAR, category VARCHAR, warehouse VARCHAR,
    current_stock INT, reorder_point INT, demand_rate NUMERIC,
    ordering_cost NUMERIC, holding_cost NUMERIC, unit_price NUMERIC,
    supplier_id INT, on_order INT, created_at TIMESTAMP, updated_at TIMESTAMP,
    supplier_name VARCHAR, supplier_tone VARCHAR, lead_days INT
) AS $$
BEGIN
    RETURN QUERY
    SELECT p.*, s.name AS supplier_name, s.tone AS supplier_tone, s.lead_days
    FROM products p
    LEFT JOIN suppliers s ON s.id = p.supplier_id
    WHERE p.current_stock <= p.reorder_point AND p.on_order <= 0
    ORDER BY (p.reorder_point - p.current_stock) DESC;
END;
$$ LANGUAGE plpgsql;


-- ── SUPPLIERS ────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION sp_supplier_list_all()
RETURNS TABLE (
    id INT, name VARCHAR, initials VARCHAR, location VARCHAR,
    lead_days INT, spend_amount NUMERIC, reliability NUMERIC, tone VARCHAR,
    created_at TIMESTAMP, active_skus BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT s.*, COUNT(p.id) AS active_skus
    FROM suppliers s
    LEFT JOIN products p ON p.supplier_id = s.id
    GROUP BY s.id ORDER BY s.name;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_supplier_find(p_id INT)
RETURNS SETOF suppliers AS $$
BEGIN
    RETURN QUERY SELECT * FROM suppliers WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_supplier_create(
    p_name VARCHAR, p_initials VARCHAR, p_location VARCHAR DEFAULT '',
    p_lead_days INT DEFAULT 0, p_spend_amount NUMERIC DEFAULT 0,
    p_reliability NUMERIC DEFAULT 90.0, p_tone VARCHAR DEFAULT 'amber'
) RETURNS INT AS $$
DECLARE
    new_id INT;
BEGIN
    INSERT INTO suppliers (name, initials, location, lead_days, spend_amount, reliability, tone)
    VALUES (p_name, p_initials, p_location, p_lead_days, p_spend_amount, p_reliability, p_tone)
    RETURNING id INTO new_id;
    RETURN new_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_supplier_update(
    p_id INT, p_name VARCHAR, p_location VARCHAR DEFAULT '',
    p_lead_days INT DEFAULT 0, p_spend_amount NUMERIC DEFAULT 0,
    p_reliability NUMERIC DEFAULT 90.0, p_tone VARCHAR DEFAULT 'amber'
) RETURNS VOID AS $$
BEGIN
    UPDATE suppliers SET
        name = p_name, location = p_location, lead_days = p_lead_days,
        spend_amount = p_spend_amount, reliability = p_reliability, tone = p_tone
    WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_supplier_delete(p_id INT)
RETURNS VOID AS $$
BEGIN
    UPDATE products SET supplier_id = NULL WHERE supplier_id = p_id;
    DELETE FROM suppliers WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;


-- ── MOVEMENTS ────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION sp_movement_record(
    p_product_id INT, p_sku VARCHAR, p_type VARCHAR, p_quantity INT,
    p_reference VARCHAR DEFAULT NULL, p_notes TEXT DEFAULT NULL,
    p_user_id INT DEFAULT NULL
) RETURNS INT AS $$
DECLARE
    new_id INT;
BEGIN
    INSERT INTO movements (product_id, sku, type, quantity, reference, notes, user_id)
    VALUES (p_product_id, p_sku, p_type, p_quantity, p_reference, p_notes, p_user_id)
    RETURNING id INTO new_id;
    RETURN new_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_movement_recent_for_product(
    p_product_id INT, p_limit INT DEFAULT 10
) RETURNS TABLE (
    id INT, type VARCHAR, quantity INT, reference VARCHAR, notes TEXT,
    created_at TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT m.id, m.type, m.quantity, m.reference, m.notes,
           to_char(m.created_at, 'YYYY-MM-DD HH24:MI') AS created_at
    FROM movements m
    WHERE m.product_id = p_product_id
    ORDER BY m.created_at DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_movement_daily_totals(p_days INT DEFAULT 14)
RETURNS TABLE(day DATE, total BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT date_trunc('day', m.created_at)::date AS day,
           COALESCE(SUM(m.quantity), 0)::BIGINT AS total
    FROM movements m
    WHERE m.created_at >= (CURRENT_DATE - (p_days - 1))
    GROUP BY day ORDER BY day;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_movement_daily_for_product(
    p_product_id INT, p_days INT DEFAULT 90
) RETURNS TABLE(day DATE, total BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT date_trunc('day', m.created_at)::date AS day,
           COALESCE(SUM(m.quantity), 0)::BIGINT AS total
    FROM movements m
    WHERE m.created_at >= (CURRENT_DATE - (p_days - 1))
      AND m.product_id = p_product_id
    GROUP BY day ORDER BY day;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_movement_units_today()
RETURNS BIGINT AS $$
DECLARE
    total BIGINT;
BEGIN
    SELECT COALESCE(SUM(quantity), 0) INTO total
    FROM movements WHERE created_at::date = CURRENT_DATE;
    RETURN total;
END;
$$ LANGUAGE plpgsql;


-- ── USERS ────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION sp_user_create(
    p_username VARCHAR, p_email VARCHAR, p_password_hash VARCHAR,
    p_role VARCHAR DEFAULT 'viewer'
) RETURNS INT AS $$
DECLARE
    new_id INT;
BEGIN
    INSERT INTO users (username, email, password_hash, role)
    VALUES (LOWER(p_username), LOWER(p_email), p_password_hash, p_role)
    RETURNING id INTO new_id;
    RETURN new_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_user_find_by_username(p_username VARCHAR)
RETURNS SETOF users AS $$
BEGIN
    RETURN QUERY SELECT * FROM users WHERE username = LOWER(p_username);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_user_find_by_email(p_email VARCHAR)
RETURNS SETOF users AS $$
BEGIN
    RETURN QUERY SELECT * FROM users WHERE email = LOWER(p_email);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_user_find_by_id(p_id INT)
RETURNS SETOF users AS $$
BEGIN
    RETURN QUERY SELECT * FROM users WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_user_record_login(p_id INT)
RETURNS VOID AS $$
BEGIN
    UPDATE users SET last_login = NOW() WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_user_list_all()
RETURNS TABLE (
    id INT, username VARCHAR, email VARCHAR, role VARCHAR,
    is_active BOOLEAN, last_login TIMESTAMP, created_at TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT u.id, u.username, u.email, u.role, u.is_active, u.last_login, u.created_at
    FROM users u ORDER BY u.created_at DESC;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_user_set_active(p_id INT, p_active BOOLEAN)
RETURNS VOID AS $$
BEGIN
    UPDATE users SET is_active = p_active WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_user_change_role(p_id INT, p_role VARCHAR)
RETURNS VOID AS $$
BEGIN
    UPDATE users SET role = p_role WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_user_set_password(p_id INT, p_password_hash VARCHAR)
RETURNS VOID AS $$
BEGIN
    UPDATE users SET password_hash = p_password_hash WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_user_find_by_oauth(p_provider VARCHAR, p_oauth_id VARCHAR)
RETURNS SETOF users AS $$
BEGIN
    RETURN QUERY
    SELECT * FROM users WHERE oauth_provider = p_provider AND oauth_id = p_oauth_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_user_create_oauth(
    p_provider VARCHAR, p_oauth_id VARCHAR, p_username VARCHAR,
    p_email VARCHAR, p_role VARCHAR DEFAULT 'viewer'
) RETURNS INT AS $$
DECLARE
    new_id INT;
BEGIN
    INSERT INTO users (username, email, oauth_provider, oauth_id, role)
    VALUES (LOWER(p_username), LOWER(p_email), p_provider, p_oauth_id, p_role)
    RETURNING id INTO new_id;
    RETURN new_id;
END;
$$ LANGUAGE plpgsql;


-- ── PASSWORD RESET TOKENS ────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION sp_reset_token_create(
    p_user_id INT, p_token_hash VARCHAR, p_expires_at TIMESTAMP
) RETURNS VOID AS $$
BEGIN
    INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
    VALUES (p_user_id, p_token_hash, p_expires_at);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_reset_token_find(p_token_hash VARCHAR)
RETURNS TABLE (
    id INT, user_id INT, token_hash VARCHAR,
    expires_at TIMESTAMP, used BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT t.id, t.user_id, t.token_hash, t.expires_at, t.used
    FROM password_reset_tokens t WHERE t.token_hash = p_token_hash;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_reset_token_consume(p_id INT)
RETURNS VOID AS $$
BEGIN
    UPDATE password_reset_tokens SET used = TRUE WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_reset_token_purge(p_user_id INT)
RETURNS VOID AS $$
BEGIN
    DELETE FROM password_reset_tokens WHERE user_id = p_user_id;
END;
$$ LANGUAGE plpgsql;


-- ── SESSIONS ─────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION sp_session_create(
    p_user_id INT, p_session_token VARCHAR,
    p_ip_address VARCHAR DEFAULT NULL, p_user_agent TEXT DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    INSERT INTO user_sessions (user_id, session_token, ip_address, user_agent)
    VALUES (p_user_id, p_session_token, p_ip_address, p_user_agent);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_session_end(p_token VARCHAR)
RETURNS VOID AS $$
BEGIN
    UPDATE user_sessions
    SET is_active = FALSE, logout_at = NOW()
    WHERE session_token = p_token;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_session_update_activity(p_token VARCHAR)
RETURNS VOID AS $$
BEGIN
    UPDATE user_sessions SET last_activity = NOW() WHERE session_token = p_token;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_session_get_active(p_user_id INT DEFAULT NULL)
RETURNS TABLE (
    id INT, user_id INT, session_token VARCHAR, ip_address VARCHAR,
    user_agent TEXT, login_at TIMESTAMP, last_activity TIMESTAMP
) AS $$
BEGIN
    IF p_user_id IS NOT NULL THEN
        RETURN QUERY
        SELECT s.id, s.user_id, s.session_token, s.ip_address,
               s.user_agent, s.login_at, s.last_activity
        FROM user_sessions s
        WHERE s.is_active = TRUE AND s.user_id = p_user_id
        ORDER BY s.last_activity DESC;
    ELSE
        RETURN QUERY
        SELECT s.id, s.user_id, s.session_token, s.ip_address,
               s.user_agent, s.login_at, s.last_activity
        FROM user_sessions s
        WHERE s.is_active = TRUE
        ORDER BY s.last_activity DESC;
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_session_cleanup_stale(p_hours INT DEFAULT 24)
RETURNS INT AS $$
DECLARE
    cleaned INT;
BEGIN
    UPDATE user_sessions
    SET is_active = FALSE, logout_at = NOW()
    WHERE is_active = TRUE
      AND last_activity < NOW() - (p_hours || ' hours')::INTERVAL;
    GET DIAGNOSTICS cleaned = ROW_COUNT;
    RETURN cleaned;
END;
$$ LANGUAGE plpgsql;


-- ── AUDIT LOG ────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION sp_audit_record(
    p_user_id INT DEFAULT NULL, p_action VARCHAR DEFAULT '',
    p_target_type VARCHAR DEFAULT NULL, p_target_id INT DEFAULT NULL,
    p_detail JSONB DEFAULT '{}', p_ip_address VARCHAR DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    INSERT INTO audit_log (user_id, action, target_type, target_id, detail, ip_address)
    VALUES (p_user_id, p_action, p_target_type, p_target_id, p_detail, p_ip_address);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_audit_recent(p_limit INT DEFAULT 50)
RETURNS TABLE (
    id INT, action VARCHAR, target_type VARCHAR, target_id INT,
    detail JSONB, created_at TIMESTAMP, username VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT a.id, a.action, a.target_type, a.target_id, a.detail,
           a.created_at, u.username
    FROM audit_log a
    LEFT JOIN users u ON u.id = a.user_id
    ORDER BY a.created_at DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_audit_count_last_hours(p_hours INT DEFAULT 24)
RETURNS BIGINT AS $$
DECLARE
    cnt BIGINT;
BEGIN
    SELECT COUNT(*) INTO cnt
    FROM audit_log WHERE created_at >= NOW() - (p_hours || ' hours')::INTERVAL;
    RETURN cnt;
END;
$$ LANGUAGE plpgsql;


-- ── SETTINGS ─────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION sp_settings_all(p_user_id INT)
RETURNS TABLE(key VARCHAR, value TEXT) AS $$
BEGIN
    RETURN QUERY
    SELECT s.key, s.value FROM user_settings s WHERE s.user_id = p_user_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_settings_set_many(p_user_id INT, p_key VARCHAR, p_value TEXT)
RETURNS VOID AS $$
BEGIN
    INSERT INTO user_settings (user_id, key, value)
    VALUES (p_user_id, p_key, p_value)
    ON CONFLICT (user_id, key)
    DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();
END;
$$ LANGUAGE plpgsql;


-- ── PURCHASE ORDERS ──────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION sp_po_list_by_status(p_status VARCHAR DEFAULT NULL)
RETURNS TABLE (
    id INT, po_number VARCHAR, supplier_id INT, product_id INT,
    quantity INT, unit_cost NUMERIC, status VARCHAR, eta_date DATE,
    created_at TIMESTAMP, updated_at TIMESTAMP,
    supplier_name VARCHAR, product_name VARCHAR, sku VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT po.*, s.name AS supplier_name, p.name AS product_name, p.sku
    FROM purchase_orders po
    LEFT JOIN suppliers s ON s.id = po.supplier_id
    LEFT JOIN products p ON p.id = po.product_id
    WHERE (p_status IS NULL OR p_status = 'all' OR po.status = p_status)
    ORDER BY po.created_at DESC;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_po_counts_by_status()
RETURNS TABLE(status VARCHAR, cnt BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT po.status, COUNT(*) AS cnt
    FROM purchase_orders po
    GROUP BY po.status;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_po_create(
    p_po_number VARCHAR, p_supplier_id INT, p_product_id INT,
    p_quantity INT, p_unit_cost NUMERIC DEFAULT 0,
    p_status VARCHAR DEFAULT 'draft', p_eta_date DATE DEFAULT NULL
) RETURNS INT AS $$
DECLARE
    new_id INT;
BEGIN
    INSERT INTO purchase_orders (po_number, supplier_id, product_id, quantity, unit_cost, status, eta_date)
    VALUES (p_po_number, p_supplier_id, p_product_id, p_quantity, p_unit_cost, p_status, p_eta_date)
    RETURNING id INTO new_id;
    RETURN new_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_po_update_status(p_id INT, p_status VARCHAR)
RETURNS VOID AS $$
BEGIN
    UPDATE purchase_orders SET status = p_status, updated_at = NOW() WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;


-- ── SETTINGS UPSERT (batch) ─────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION sp_settings_upsert_batch(
    p_user_id INT, p_keys TEXT[], p_values TEXT[]
) RETURNS VOID AS $$
DECLARE
    i INT;
BEGIN
    FOR i IN 1..array_length(p_keys, 1) LOOP
        INSERT INTO user_settings (user_id, key, value)
        VALUES (p_user_id, p_keys[i], p_values[i])
        ON CONFLICT (user_id, key)
        DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();
    END LOOP;
END;
$$ LANGUAGE plpgsql;
