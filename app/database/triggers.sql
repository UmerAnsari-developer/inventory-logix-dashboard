-- =============================================================================
-- InventoryLogix — Triggers for Session Monitoring & Audit Logging
-- Auto-records login, logout, signup events to warehouse fact tables
-- =============================================================================

-- ── FUNCTION: current_app_user_id() — Read transaction-local app user ID ───────
-- Reads the GUC 'app.current_user_id' set via set_config() in the application layer.
-- Returns NULL if not set or not a valid integer. Used by audit triggers to
-- attribute changes to the current application user without passing user_id explicitly.

CREATE OR REPLACE FUNCTION current_app_user_id() RETURNS bigint
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_user_id text;
    v_result bigint;
BEGIN
    v_user_id := current_setting('app.current_user_id', true);
    
    IF v_user_id IS NULL OR v_user_id = '' THEN
        RETURN NULL;
    END IF;
    
    BEGIN
        v_result := v_user_id::bigint;
        RETURN v_result;
    EXCEPTION WHEN invalid_text_representation THEN
        RETURN NULL;
    END;
END;
$$;

GRANT EXECUTE ON FUNCTION current_app_user_id() TO postgres;

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

-- Fix DB-012: the function above existed but was never attached, so stale
-- sessions accumulated forever. Each login now sweeps sessions idle > 24h
-- (cheap: partial index idx_user_sessions_active scopes the UPDATE).
DROP TRIGGER IF EXISTS trg_session_cleanup ON user_sessions;
CREATE TRIGGER trg_session_cleanup
    AFTER INSERT ON user_sessions
    FOR EACH ROW
    EXECUTE FUNCTION trg_cleanup_stale_sessions();


-- ── FUNCTION: Track product changes for audit ────────────────────────────────

CREATE OR REPLACE FUNCTION trg_log_product_change()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
        VALUES (current_app_user_id(), 'product_created', 'product', NEW.id,
                jsonb_build_object('sku', NEW.sku, 'name', NEW.name));
    ELSIF TG_OP = 'UPDATE' THEN
        -- DB-068: soft delete (deleted_at NULL -> NOT NULL) is an UPDATE to the
        -- database but a DELETE to the business — log it as product_deleted.
        IF NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL THEN
            INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
            VALUES (current_app_user_id(), 'product_deleted', 'product', OLD.id,
                    jsonb_build_object('sku', OLD.sku, 'name', OLD.name));
        ELSE
            INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
            VALUES (current_app_user_id(), 'product_updated', 'product', NEW.id,
                    jsonb_build_object('sku', NEW.sku, 'name', NEW.name));
        END IF;
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
        VALUES (current_app_user_id(), 'product_deleted', 'product', OLD.id,
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
        INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
        VALUES (current_app_user_id(), 'supplier_created', 'supplier', NEW.id,
                jsonb_build_object('name', NEW.name));
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
        VALUES (current_app_user_id(), 'supplier_updated', 'supplier', NEW.id,
                jsonb_build_object('name', NEW.name));
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
        VALUES (current_app_user_id(), 'supplier_deleted', 'supplier', OLD.id,
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
    INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
    VALUES (
        current_app_user_id(),
        'movement_' || LOWER(NEW.type),
        'movement',
        NEW.id,
        jsonb_build_object(
            'product_id', NEW.product_id,
            'sku', (SELECT sku FROM products WHERE id = NEW.product_id),
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
        INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
        VALUES (current_app_user_id(), 'po_created', 'purchase_order', NEW.id,
                jsonb_build_object('po_number', NEW.po_number, 'status', NEW.status));
    ELSIF TG_OP = 'UPDATE' AND OLD.status != NEW.status THEN
        INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
        VALUES (current_app_user_id(), 'po_status_changed', 'purchase_order', NEW.id,
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
