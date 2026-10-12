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
          AND (p_category = '' OR p.category = ANY(string_to_array(p_category, ',')))
          AND (p_warehouse = '' OR p.warehouse = ANY(string_to_array(p_warehouse, ',')))
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

-- DB-021: drop the legacy 11-param overload (had p_current_stock). It makes
-- calls with NULL args ambiguous once the 10-param version exists.
DROP FUNCTION IF EXISTS sp_product_update(integer, varchar, varchar, varchar, numeric, integer, integer, integer, numeric, numeric, numeric);
CREATE OR REPLACE FUNCTION sp_product_update(
    p_id INT, p_name VARCHAR, p_category VARCHAR DEFAULT '',
    p_warehouse VARCHAR DEFAULT 'WH-Pune', p_unit_price NUMERIC DEFAULT 0,
    p_supplier_id INT DEFAULT NULL, p_reorder_point INT DEFAULT 0,
    p_demand_rate NUMERIC DEFAULT 0, p_ordering_cost NUMERIC DEFAULT 0,
    p_holding_cost NUMERIC DEFAULT 0
) RETURNS VOID AS $$
BEGIN
    -- DB-021: current_stock is intentionally NOT updated here.
    -- Stock changes ONLY via sp_movement_record (atomic delta + ledger).
    UPDATE products SET
        name = p_name, category = p_category, warehouse = p_warehouse,
        unit_price = p_unit_price, supplier_id = p_supplier_id,
        reorder_point = p_reorder_point,
        demand_rate = p_demand_rate, ordering_cost = p_ordering_cost,
        holding_cost = p_holding_cost, updated_at = NOW()
    WHERE id = p_id;
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

-- suppliers gained deleted_at (schema.sql:40); the OUT row type differs from
-- older installs, so CREATE OR REPLACE alone cannot update it.
DROP FUNCTION IF EXISTS sp_supplier_list_all();

CREATE OR REPLACE FUNCTION sp_supplier_list_all()
RETURNS TABLE (
    id INT, name VARCHAR, initials VARCHAR, location VARCHAR,
    lead_days INT, spend_amount NUMERIC, reliability NUMERIC, tone VARCHAR,
    created_at TIMESTAMP, deleted_at TIMESTAMP, active_skus BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT s.*, COUNT(p.id) AS active_skus
    FROM suppliers s
    LEFT JOIN products p ON p.supplier_id = s.id
    WHERE s.deleted_at IS NULL
    GROUP BY s.id ORDER BY s.name;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_supplier_find(p_id INT)
RETURNS SETOF suppliers AS $$
BEGIN
    RETURN QUERY SELECT * FROM suppliers WHERE id = p_id AND deleted_at IS NULL;
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

-- Soft delete (fix DB-004): keep supplier rows so products, purchase orders and
-- audit history retain their references; visibility filters exclude deleted rows.
CREATE OR REPLACE FUNCTION sp_supplier_delete(p_id INT)
RETURNS VOID AS $$
BEGIN
    UPDATE suppliers SET deleted_at = NOW() WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;


-- ── MOVEMENTS ────────────────────────────────────────────────────────────────

-- Atomic movement recording (fix DB-002): validate stock, insert the movement
-- and adjust stock inside ONE transaction while holding the product row lock.
-- The lock is held until the caller commits, so concurrent OUT movements cannot
-- read a stale balance or overwrite each other's absolute stock write.
CREATE OR REPLACE FUNCTION sp_movement_record(
    p_product_id INT, p_type VARCHAR, p_quantity INT,
    p_reference VARCHAR DEFAULT NULL, p_notes TEXT DEFAULT NULL,
    p_user_id INT DEFAULT NULL
) RETURNS INT AS $$
DECLARE
    new_id INT;
    v_stock INT;
    v_delta INT;
BEGIN
    SELECT current_stock INTO v_stock
    FROM products
    WHERE id = p_product_id AND deleted_at IS NULL
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Invalid product_id %: product does not exist', p_product_id;
    END IF;

    IF p_type IN ('IN', 'RETURN', 'ADJUSTMENT') THEN
        v_delta := p_quantity;
    ELSIF p_type = 'OUT' THEN
        v_delta := -p_quantity;
    ELSE
        RAISE EXCEPTION 'Invalid movement type %', p_type;
    END IF;

    v_stock := COALESCE(v_stock, 0);
    IF v_stock + v_delta < 0 THEN
        RAISE EXCEPTION 'Insufficient stock: have %, need %', v_stock, p_quantity;
    END IF;

    -- Insert first so trg_validate_movement checks against the pre-update balance,
    -- then apply the delta (both in this transaction — atomic by construction).
    INSERT INTO movements (product_id, type, quantity, reference, notes, user_id)
    VALUES (p_product_id, p_type, p_quantity, p_reference, p_notes, p_user_id)
    RETURNING id INTO new_id;

    UPDATE products
    SET current_stock = v_stock + v_delta, updated_at = NOW()
    WHERE id = p_product_id;

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
      AND m.deleted_at IS NULL
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

CREATE OR REPLACE FUNCTION sp_movement_daily_inout(p_days INT DEFAULT 14)
RETURNS TABLE(day DATE, in_qty BIGINT, out_qty BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT date_trunc('day', m.created_at)::date AS day,
           COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.quantity ELSE 0 END), 0)::BIGINT AS in_qty,
           COALESCE(SUM(CASE WHEN m.type = 'OUT' THEN m.quantity ELSE 0 END), 0)::BIGINT AS out_qty
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
    SELECT d.day::date,
           COALESCE(m.total, 0)::BIGINT AS total
    FROM generate_series(
             (CURRENT_DATE - (p_days - 1))::date,
             CURRENT_DATE,
             '1 day'::interval
         ) AS d(day)
    LEFT JOIN (
        SELECT date_trunc('day', m.created_at)::date AS day,
               COALESCE(SUM(CASE WHEN m.type = 'OUT' THEN m.quantity ELSE 0 END), 0)::BIGINT AS total
        FROM movements m
        WHERE m.created_at >= (CURRENT_DATE - (p_days - 1))
          AND m.product_id = p_product_id
        GROUP BY day
    ) m ON m.day = d.day::date
    ORDER BY d.day;
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
    FROM password_reset_tokens t
    WHERE t.token_hash = p_token_hash
      AND t.used = FALSE
      AND t.expires_at > (NOW() AT TIME ZONE 'UTC');
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
    VALUES (COALESCE(p_user_id, current_app_user_id()), p_action, p_target_type, p_target_id, p_detail, p_ip_address);
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
    SELECT po.id, po.po_number, po.supplier_id, po.product_id,
           po.quantity, po.unit_cost, po.status, po.eta_date,
           po.created_at, po.updated_at,
           s.name AS supplier_name, p.name AS product_name, p.sku
    FROM purchase_orders po
    LEFT JOIN suppliers s ON s.id = po.supplier_id
    LEFT JOIN products p ON p.id = po.product_id
    WHERE po.deleted_at IS NULL
      AND (p_status IS NULL OR p_status = 'all' OR po.status = p_status)
    ORDER BY po.created_at DESC;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_po_counts_by_status()
RETURNS TABLE(status VARCHAR, cnt BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT po.status, COUNT(*) AS cnt
    FROM purchase_orders po
    WHERE po.deleted_at IS NULL
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

-- PO state machine (fix DB-003/DB-024): validates the transition, applies stock and
-- on_order effects atomically, and is idempotent (same-status = no-op).
--   draft -> approved | cancelled
--   approved -> in_transit | cancelled
--   in_transit -> received | cancelled
--   received / cancelled are terminal.
-- DB-024: on 'received', insert a movement via sp_movement_record (ledger + stock delta)
-- instead of direct stock UPDATE. This ensures the ledger row exists and reuses
-- the atomic stock adjustment logic (row lock, delta, negative guard).
CREATE OR REPLACE FUNCTION sp_po_transition(p_id INT, p_new_status VARCHAR)
RETURNS VOID AS $$
DECLARE
    po purchase_orders%ROWTYPE;
BEGIN
    SELECT * INTO po FROM purchase_orders
    WHERE id = p_id AND deleted_at IS NULL
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Purchase order % not found', p_id;
    END IF;
    IF po.status = p_new_status THEN
        RETURN;  -- idempotent re-apply
    END IF;
    IF NOT (
        (po.status = 'draft'       AND p_new_status IN ('approved', 'cancelled')) OR
        (po.status = 'approved'    AND p_new_status IN ('in_transit', 'cancelled')) OR
        (po.status = 'in_transit'  AND p_new_status IN ('received', 'cancelled'))
    ) THEN
        RAISE EXCEPTION 'Invalid PO transition: % -> %', po.status, p_new_status;
    END IF;

    IF po.product_id IS NOT NULL AND p_new_status = 'received' THEN
        -- DB-024: route through the atomic movement funnel (ledger + stock delta)
        PERFORM sp_movement_record(po.product_id, 'IN', po.quantity,
                                   po.po_number, 'PO received', NULL);
        UPDATE products
        SET on_order = GREATEST(on_order - po.quantity, 0),
            updated_at = NOW()
        WHERE id = po.product_id;
    ELSIF po.product_id IS NOT NULL AND p_new_status = 'cancelled' THEN
        UPDATE products
        SET on_order = GREATEST(on_order - po.quantity, 0),
            updated_at = NOW()
        WHERE id = po.product_id;
    END IF;

    UPDATE purchase_orders SET status = p_new_status, updated_at = NOW() WHERE id = p_id;
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
-- =============================================================================
-- UPDATED PROCEDURES FOR INTEGRITY FIXES
-- =============================================================================

-- Users
DROP FUNCTION IF EXISTS sp_user_delete(integer);
CREATE FUNCTION sp_user_delete(p_id INT)
RETURNS VOID AS $$
BEGIN
    UPDATE users SET deleted_at = NOW() WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

-- User list and find functions (filter deleted_at)
DROP FUNCTION IF EXISTS sp_user_list_all();
CREATE FUNCTION sp_user_list_all()
RETURNS TABLE (
    id INT, username VARCHAR, email VARCHAR, role VARCHAR,
    is_active BOOLEAN, last_login TIMESTAMP, created_at TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT u.id, u.username, u.email, u.role, u.is_active, u.last_login, u.created_at
    FROM users u
    WHERE u.deleted_at IS NULL
    ORDER BY u.created_at DESC;
END;
$$ LANGUAGE plpgsql;

DROP FUNCTION IF EXISTS sp_user_find_by_id(integer);
CREATE FUNCTION sp_user_find_by_id(p_id INT)
RETURNS SETOF users AS $$
BEGIN
    RETURN QUERY SELECT * FROM users WHERE id = p_id AND deleted_at IS NULL;
END;
$$ LANGUAGE plpgsql;

DROP FUNCTION IF EXISTS sp_user_find_by_username(varchar);
CREATE FUNCTION sp_user_find_by_username(p_username VARCHAR)
RETURNS SETOF users AS $$
BEGIN
    RETURN QUERY SELECT * FROM users WHERE username = LOWER(p_username) AND deleted_at IS NULL;
END;
$$ LANGUAGE plpgsql;

DROP FUNCTION IF EXISTS sp_user_find_by_email(varchar);
CREATE FUNCTION sp_user_find_by_email(p_email VARCHAR)
RETURNS SETOF users AS $$
BEGIN
    RETURN QUERY SELECT * FROM users WHERE email = LOWER(p_email) AND deleted_at IS NULL;
END;
$$ LANGUAGE plpgsql;

-- Products
DROP FUNCTION IF EXISTS sp_product_delete(integer);
CREATE FUNCTION sp_product_delete(p_id INT)
RETURNS VOID AS $$
BEGIN
    UPDATE products SET deleted_at = NOW() WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

-- Movements / purchase orders soft delete (GAP-020 phase 1) — mirrors
-- sp_product_delete. Analytics/ETL stay unfiltered until phase 2 (documented).
CREATE OR REPLACE FUNCTION sp_movement_soft_delete(p_id INT)
RETURNS VOID AS $$
BEGIN
    UPDATE movements SET deleted_at = NOW() WHERE id = p_id AND deleted_at IS NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_po_soft_delete(p_id INT)
RETURNS VOID AS $$
BEGIN
    UPDATE purchase_orders SET deleted_at = NOW() WHERE id = p_id AND deleted_at IS NULL;
END;
$$ LANGUAGE plpgsql;

DROP FUNCTION IF EXISTS sp_product_list(text, text, text, text, integer, integer);
CREATE FUNCTION sp_product_list(
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
        SELECT p.id, p.sku, p.name, p.category, p.warehouse, p.current_stock, p.reorder_point, p.demand_rate, p.ordering_cost, p.holding_cost, p.unit_price, p.supplier_id, p.on_order, p.created_at, p.updated_at,
               s.name AS supplier_name, s.tone AS supplier_tone, s.lead_days
        FROM products p
        LEFT JOIN suppliers s ON s.id = p.supplier_id
        WHERE (p_search = '' OR p.sku ILIKE '%' || p_search || '%'
                OR p.name ILIKE '%' || p_search || '%'
                OR p.category ILIKE '%' || p_search || '%'
                OR s.name ILIKE '%' || p_search || '%')
      AND (p_category = '' OR p.category = ANY(string_to_array(p_category, ',')))
      AND (p_warehouse = '' OR p.warehouse = ANY(string_to_array(p_warehouse, ',')))
      AND (p_status = '' OR
            (p_status = 'ok' AND p.current_stock > p.reorder_point) OR
            (p_status = 'low' AND p.current_stock <= p.reorder_point AND p.current_stock > 0) OR
            (p_status = 'out' AND p.current_stock <= 0))
      AND p.deleted_at IS NULL
    )
    SELECT f.*, (SELECT COUNT(*) FROM filtered) AS total_count
    FROM filtered f
    ORDER BY f.sku
    LIMIT p_limit OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;

DROP FUNCTION IF EXISTS sp_product_find(integer);
CREATE FUNCTION sp_product_find(p_id INT)
RETURNS SETOF products AS $$
BEGIN
    RETURN QUERY SELECT * FROM products WHERE id = p_id AND deleted_at IS NULL;
END;
$$ LANGUAGE plpgsql;

DROP FUNCTION IF EXISTS sp_product_find_by_sku(varchar);
CREATE FUNCTION sp_product_find_by_sku(p_sku VARCHAR)
RETURNS SETOF products AS $$
BEGIN
    RETURN QUERY SELECT * FROM products WHERE sku = p_sku AND deleted_at IS NULL;
END;
$$ LANGUAGE plpgsql;

-- Low stock products (exclude deleted, explicit columns)
DROP FUNCTION IF EXISTS sp_product_low_stock();
CREATE FUNCTION sp_product_low_stock()
RETURNS TABLE (
    id INT, sku VARCHAR, name VARCHAR, category VARCHAR, warehouse VARCHAR,
    current_stock INT, reorder_point INT, demand_rate NUMERIC,
    ordering_cost NUMERIC, holding_cost NUMERIC, unit_price NUMERIC,
    supplier_id INT, on_order INT, created_at TIMESTAMP, updated_at TIMESTAMP,
    supplier_name VARCHAR, supplier_tone VARCHAR, lead_days INT
) AS $$
BEGIN
    RETURN QUERY
    SELECT p.id, p.sku, p.name, p.category, p.warehouse, p.current_stock, p.reorder_point, p.demand_rate, p.ordering_cost, p.holding_cost, p.unit_price, p.supplier_id, p.on_order, p.created_at, p.updated_at,
           s.name AS supplier_name, s.tone AS supplier_tone, s.lead_days
    FROM products p
    LEFT JOIN suppliers s ON s.id = p.supplier_id
    WHERE p.current_stock <= p.reorder_point AND p.on_order <= 0
      AND p.deleted_at IS NULL
    ORDER BY (p.reorder_point - p.current_stock) DESC;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- ADMIN TABLES SOFT DELETE PROCEDURES
-- =============================================================================

-- System Backups
CREATE OR REPLACE FUNCTION sp_system_backup_list(
    p_limit INT DEFAULT 100,
    p_offset INT DEFAULT 0,
    p_include_deleted BOOLEAN DEFAULT FALSE
) RETURNS TABLE (
    id INT, backup_name VARCHAR, backup_type VARCHAR, file_path VARCHAR,
    size BIGINT, status VARCHAR, created_at TIMESTAMP, created_by INT,
    deleted_at TIMESTAMP, encrypted BOOLEAN, encryption_key_id VARCHAR, checksum VARCHAR,
    total_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    WITH filtered AS (
        SELECT *
        FROM system_backups
        WHERE (p_include_deleted = TRUE OR deleted_at IS NULL)
        ORDER BY created_at DESC
    )
    SELECT f.*, (SELECT COUNT(*) FROM filtered) AS total_count
    FROM filtered f
    LIMIT p_limit OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_system_backup_find(p_id INT)
RETURNS SETOF system_backups AS $$
BEGIN
    RETURN QUERY SELECT * FROM system_backups WHERE id = p_id AND deleted_at IS NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_system_backup_delete(p_id INT)
RETURNS VOID AS $$
BEGIN
    UPDATE system_backups SET deleted_at = NOW() WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

-- System Config Overrides
CREATE OR REPLACE FUNCTION sp_system_config_override_list(
    p_limit INT DEFAULT 100,
    p_offset INT DEFAULT 0,
    p_include_deleted BOOLEAN DEFAULT FALSE
) RETURNS TABLE (
    id INT, key VARCHAR, value TEXT, description TEXT, is_sensitive BOOLEAN,
    updated_at TIMESTAMP, updated_by INT, deleted_at TIMESTAMP,
    total_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    WITH filtered AS (
        SELECT *
        FROM system_config_overrides
        WHERE (p_include_deleted = TRUE OR deleted_at IS NULL)
        ORDER BY updated_at DESC
    )
    SELECT f.*, (SELECT COUNT(*) FROM filtered) AS total_count
    FROM filtered f
    LIMIT p_limit OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_system_config_override_find(p_id INT)
RETURNS SETOF system_config_overrides AS $$
BEGIN
    RETURN QUERY SELECT * FROM system_config_overrides WHERE id = p_id AND deleted_at IS NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_system_config_override_delete(p_id INT)
RETURNS VOID AS $$
BEGIN
    UPDATE system_config_overrides SET deleted_at = NOW() WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

-- Scheduled Audit Reports
CREATE OR REPLACE FUNCTION sp_scheduled_audit_report_list(
    p_limit INT DEFAULT 100,
    p_offset INT DEFAULT 0,
    p_active_only BOOLEAN DEFAULT FALSE,
    p_include_deleted BOOLEAN DEFAULT FALSE
) RETURNS TABLE (
    id INT, name VARCHAR, description TEXT, format VARCHAR, frequency VARCHAR,
    parameters JSON, next_run_time TIMESTAMP, last_run_time TIMESTAMP,
    is_active BOOLEAN, created_at TIMESTAMP, updated_at TIMESTAMP,
    created_by INT, updated_by INT, deleted_at TIMESTAMP,
    total_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    WITH filtered AS (
        SELECT *
        FROM scheduled_audit_reports
        WHERE (p_include_deleted = TRUE OR deleted_at IS NULL)
          AND (p_active_only = FALSE OR is_active = TRUE)
        ORDER BY created_at DESC
    )
    SELECT f.*, (SELECT COUNT(*) FROM filtered) AS total_count
    FROM filtered f
    LIMIT p_limit OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_scheduled_audit_report_find(p_id INT)
RETURNS SETOF scheduled_audit_reports AS $$
BEGIN
    RETURN QUERY SELECT * FROM scheduled_audit_reports WHERE id = p_id AND deleted_at IS NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_scheduled_audit_report_delete(p_id INT)
RETURNS VOID AS $$
BEGIN
    UPDATE scheduled_audit_reports SET deleted_at = NOW() WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

-- Idempotency Keys
CREATE OR REPLACE FUNCTION sp_idempotency_check(p_key VARCHAR, p_user_id INT)
RETURNS JSONB AS $$
DECLARE
    v_response JSONB;
BEGIN
    SELECT response_json INTO v_response
    FROM idempotency_keys
    WHERE key = p_key AND user_id = p_user_id;
    RETURN v_response;
END;
$$ LANGUAGE plpgsql;

-- L2 fix: reserve the key BEFORE executing the endpoint (single txn).
-- Returns TRUE if this caller owns the key (inserted), FALSE if already
-- reserved by a concurrent request — closing the check-then-act race.
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

CREATE OR REPLACE FUNCTION sp_idempotency_record(p_key VARCHAR, p_user_id INT, p_response JSONB)
RETURNS VOID AS $$
BEGIN
    INSERT INTO idempotency_keys (key, user_id, response_json)
    VALUES (p_key, p_user_id, p_response)
    ON CONFLICT (key, user_id) DO UPDATE SET response_json = EXCLUDED.response_json;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_idempotency_cleanup(p_older_than INTERVAL DEFAULT '30 days')
RETURNS INTEGER AS $$
DECLARE
    v_deleted INT;
BEGIN
    DELETE FROM idempotency_keys
    WHERE created_at < NOW() - p_older_than;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

-- ─────────────────────────────────────────────────────────────────
-- DB-044: Retention purges for audit/ops tables.
-- forecast/anomaly/fact tables intentionally NOT purged — they hold
-- business history. Ops tables only.
-- ─────────────────────────────────────────────────────────────────

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

-- =============================================================================
-- JOB QUEUE (GAP-012) — Persistent job queue with pg_cron scheduling
-- =============================================================================

-- Process up to batch_size pending jobs
-- Returns number of jobs dispatched
CREATE OR REPLACE FUNCTION job_queue_process_batch(batch_size INT DEFAULT 100)
RETURNS INT LANGUAGE plpgsql AS $$
DECLARE
    j RECORD;
    processed INT := 0;
BEGIN
    FOR j IN
        SELECT * FROM job_queue
        WHERE status = 'pending' AND next_run <= now()
        ORDER BY priority DESC, created_at
        FOR UPDATE SKIP LOCKED
        LIMIT batch_size
    LOOP
        -- Try to acquire advisory lock for this job.
        -- hashtext returns int4; j.id is BIGINT — cast to int so the
        -- two-key overload pg_try_advisory_xact_lock(int4, int4) resolves.
        IF pg_try_advisory_xact_lock(hashtext(j.task_name || ':' || j.id)) THEN
            UPDATE job_queue
            SET status = 'running', locked_by = inet_server_addr()||':'||pg_backend_pid(), started_at = now()
            WHERE id = j.id AND status = 'pending';
            
            -- Notify external worker via pg_notify
            PERFORM pg_notify('job_queue', json_build_object(
                'job_id', j.id, 'task', j.task_name, 'payload', j.payload
            )::text);
            
            processed := processed + 1;
        END IF;
    END LOOP;
    RETURN processed;
END $$;

-- Cleanup old completed/failed jobs
CREATE OR REPLACE FUNCTION job_queue_cleanup(retention INTERVAL DEFAULT '30 days')
RETURNS INT LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM job_queue
    WHERE status IN ('completed', 'failed', 'dead')
      AND completed_at < now() - retention;
    RETURN ROW_COUNT;
END $$;

-- Get job status
CREATE OR REPLACE FUNCTION job_queue_get_status(p_job_id BIGINT)
RETURNS TABLE (
    id BIGINT, task_name TEXT, status TEXT, attempts INT, max_attempts INT,
    created_at TIMESTAMPTZ, started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
    error TEXT, result JSONB
) LANGUAGE sql AS $$
    SELECT id, task_name, status, attempts, max_attempts,
           created_at, started_at, completed_at, error, result
    FROM job_queue WHERE id = p_job_id;
$$;

-- Enqueue a job (helper function)
CREATE OR REPLACE FUNCTION job_queue_enqueue(
    p_task_name TEXT,
    p_payload JSONB DEFAULT '{}',
    p_priority INT DEFAULT 0,
    p_max_attempts INT DEFAULT 3,
    p_delay_seconds INT DEFAULT 0
)
RETURNS TABLE (id BIGINT) LANGUAGE plpgsql AS $$
DECLARE
    v_next_run TIMESTAMPTZ;
BEGIN
    v_next_run := now();
    IF p_delay_seconds > 0 THEN
        v_next_run := now() + (p_delay_seconds || ' seconds')::interval;
    END IF;
    
    RETURN QUERY
    INSERT INTO job_queue (task_name, payload, priority, max_attempts, next_run)
    VALUES (p_task_name, p_payload, p_priority, p_max_attempts, v_next_run)
    RETURNING job_queue.id;
END $$;
