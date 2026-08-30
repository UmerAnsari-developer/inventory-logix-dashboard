-- =============================================================================
-- InventoryLogix — Triggers for Session Monitoring & Audit Logging
-- Auto-records login, logout, signup events to warehouse fact tables
-- =============================================================================

-- ── FUNCTION: Log user signup to audit_log ───────────────────────────────────

CREATE OR REPLACE FUNCTION trg_log_user_signup()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
    VALUES (
        NEW.id,
        'signup_success',
        'user',
        NEW.id,
        jsonb_build_object(
            'username', NEW.username,
            'email', NEW.email,
            'role', NEW.role,
            'method', CASE WHEN NEW.oauth_provider IS NOT NULL THEN 'oauth' ELSE 'form' END,
            'oauth_provider', NEW.oauth_provider
        )
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ── TRIGGER: On new user created ─────────────────────────────────────────────

DROP TRIGGER IF EXISTS trg_user_signup ON users;
CREATE TRIGGER trg_user_signup
    AFTER INSERT ON users
    FOR EACH ROW
    EXECUTE FUNCTION trg_log_user_signup();


-- ── FUNCTION: Log session creation (login) to audit_log ──────────────────────

CREATE OR REPLACE FUNCTION trg_log_session_create()
RETURNS TRIGGER AS $$
DECLARE
    v_username VARCHAR;
BEGIN
    SELECT username INTO v_username FROM users WHERE id = NEW.user_id;

    INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
    VALUES (
        NEW.user_id,
        'login_success',
        'session',
        NEW.id,
        jsonb_build_object(
            'username', COALESCE(v_username, 'unknown'),
            'session_token', NEW.session_token,
            'ip_address', NEW.ip_address,
            'user_agent', NEW.user_agent,
            'method', 'session_create'
        )
    );

    -- Also update users.last_login
    UPDATE users SET last_login = NOW() WHERE id = NEW.user_id;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ── TRIGGER: On session created (login) ──────────────────────────────────────

DROP TRIGGER IF EXISTS trg_session_create ON user_sessions;
CREATE TRIGGER trg_session_create
    AFTER INSERT ON user_sessions
    FOR EACH ROW
    EXECUTE FUNCTION trg_log_session_create();


-- ── FUNCTION: Log session end (logout) to audit_log ──────────────────────────

CREATE OR REPLACE FUNCTION trg_log_session_end()
RETURNS TRIGGER AS $$
DECLARE
    v_username VARCHAR;
BEGIN
    -- Only log when session transitions from active to inactive
    IF OLD.is_active = TRUE AND NEW.is_active = FALSE THEN
        SELECT username INTO v_username FROM users WHERE id = NEW.user_id;

        INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
        VALUES (
            NEW.user_id,
            'logout',
            'session',
            NEW.id,
            jsonb_build_object(
                'username', COALESCE(v_username, 'unknown'),
                'session_token', NEW.session_token,
                'ip_address', NEW.ip_address,
                'duration_sec', EXTRACT(EPOCH FROM (NEW.logout_at - NEW.login_at))::INTEGER
            )
        );
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ── TRIGGER: On session updated (logout) ─────────────────────────────────────

DROP TRIGGER IF EXISTS trg_session_end ON user_sessions;
CREATE TRIGGER trg_session_end
    AFTER UPDATE ON user_sessions
    FOR EACH ROW
    WHEN (OLD.is_active = TRUE AND NEW.is_active = FALSE)
    EXECUTE FUNCTION trg_log_session_end();


-- ── FUNCTION: Auto-cleanup stale sessions on any session read ────────────────
-- Runs cleanup when a stale session is accessed

CREATE OR REPLACE FUNCTION trg_cleanup_stale_sessions()
RETURNS TRIGGER AS $$
BEGIN
    -- Mark sessions inactive if no activity for 24 hours
    UPDATE user_sessions
    SET is_active = FALSE, logout_at = NOW()
    WHERE is_active = TRUE
      AND last_activity < NOW() - INTERVAL '24 hours'
      AND id != NEW.id;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ── FUNCTION: Track product changes for audit ────────────────────────────────

CREATE OR REPLACE FUNCTION trg_log_product_change()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_log (action, target_type, target_id, detail)
        VALUES ('product_created', 'product', NEW.id,
                jsonb_build_object('sku', NEW.sku, 'name', NEW.name));
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO audit_log (action, target_type, target_id, detail)
        VALUES ('product_updated', 'product', NEW.id,
                jsonb_build_object('sku', NEW.sku, 'name', NEW.name));
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO audit_log (action, target_type, target_id, detail)
        VALUES ('product_deleted', 'product', OLD.id,
                jsonb_build_object('sku', OLD.sku, 'name', OLD.name));
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_product_audit ON products;
CREATE TRIGGER trg_product_audit
    AFTER INSERT OR UPDATE OR DELETE ON products
    FOR EACH ROW
    EXECUTE FUNCTION trg_log_product_change();


-- ── FUNCTION: Track supplier changes ─────────────────────────────────────────

CREATE OR REPLACE FUNCTION trg_log_supplier_change()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_log (action, target_type, target_id, detail)
        VALUES ('supplier_created', 'supplier', NEW.id,
                jsonb_build_object('name', NEW.name));
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO audit_log (action, target_type, target_id, detail)
        VALUES ('supplier_updated', 'supplier', NEW.id,
                jsonb_build_object('name', NEW.name));
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO audit_log (action, target_type, target_id, detail)
        VALUES ('supplier_deleted', 'supplier', OLD.id,
                jsonb_build_object('name', OLD.name));
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_supplier_audit ON suppliers;
CREATE TRIGGER trg_supplier_audit
    AFTER INSERT OR UPDATE OR DELETE ON suppliers
    FOR EACH ROW
    EXECUTE FUNCTION trg_log_supplier_change();


-- ── FUNCTION: Validate movement + auto-populate SKU from product_id ──────────

CREATE OR REPLACE FUNCTION trg_validate_movement()
RETURNS TRIGGER AS $$
DECLARE
    v_sku VARCHAR;
    v_stock INT;
BEGIN
    -- Auto-populate SKU from product_id (never trust caller-provided SKU)
    SELECT sku, current_stock INTO v_sku, v_stock FROM products WHERE id = NEW.product_id;
    IF v_sku IS NULL THEN
        RAISE EXCEPTION 'Invalid product_id %: product does not exist', NEW.product_id;
    END IF;
    NEW.sku := v_sku;

    -- Prevent negative stock on OUT and ADJUSTMENT
    IF NEW.type = 'OUT' AND v_stock - NEW.quantity < 0 THEN
        RAISE EXCEPTION 'Insufficient stock: have %, need %', v_stock, NEW.quantity;
    END IF;
    IF NEW.type = 'ADJUSTMENT' AND v_stock + NEW.quantity < 0 THEN
        RAISE EXCEPTION 'Adjustment would create negative stock: have %, adjustment %', v_stock, NEW.quantity;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_validate_movement ON movements;
CREATE TRIGGER trg_validate_movement
    BEFORE INSERT ON movements
    FOR EACH ROW
    EXECUTE FUNCTION trg_validate_movement();


-- ── FUNCTION: Log movement creation to audit ────────────────────────────────

CREATE OR REPLACE FUNCTION trg_log_movement_create()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO audit_log (action, target_type, target_id, detail)
    VALUES (
        'movement_' || LOWER(NEW.type),
        'movement',
        NEW.id,
        jsonb_build_object(
            'product_id', NEW.product_id,
            'sku', NEW.sku,
            'type', NEW.type,
            'quantity', NEW.quantity,
            'reference', NEW.reference
        )
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_movement_stock_update ON movements;
CREATE TRIGGER trg_movement_stock_update
    AFTER INSERT ON movements
    FOR EACH ROW
    EXECUTE FUNCTION trg_log_movement_create();


-- ── FUNCTION: Track PO status changes ────────────────────────────────────────

CREATE OR REPLACE FUNCTION trg_log_po_change()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_log (action, target_type, target_id, detail)
        VALUES ('po_created', 'purchase_order', NEW.id,
                jsonb_build_object('po_number', NEW.po_number, 'status', NEW.status));
    ELSIF TG_OP = 'UPDATE' AND OLD.status != NEW.status THEN
        INSERT INTO audit_log (action, target_type, target_id, detail)
        VALUES ('po_status_changed', 'purchase_order', NEW.id,
                jsonb_build_object(
                    'po_number', NEW.po_number,
                    'old_status', OLD.status,
                    'new_status', NEW.status
                ));
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_po_audit ON purchase_orders;
CREATE TRIGGER trg_po_audit
    AFTER INSERT OR UPDATE ON purchase_orders
    FOR EACH ROW
    EXECUTE FUNCTION trg_log_po_change();
