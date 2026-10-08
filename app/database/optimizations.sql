-- =============================================================================
-- InventoryLogix — Database Performance Optimizations
-- Run this after the main schema is applied
-- =============================================================================

-- ── 1. MISSING FOREIGN KEY INDEXES ───────────────────────────────────────────

-- Products supplier_id index (already exists in schema.sql line 83)
-- But let's ensure it exists with proper naming
CREATE INDEX IF NOT EXISTS idx_products_supplier_id ON products(supplier_id);

-- Purchase orders indexes (CRITICAL - missing in schema)
CREATE INDEX IF NOT EXISTS idx_purchase_orders_supplier_id ON purchase_orders(supplier_id);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_product_id ON purchase_orders(product_id);

-- Improve movements index for common query patterns
DROP INDEX IF EXISTS idx_movements_product_created;
CREATE INDEX idx_movements_product_created ON movements(product_id, created_at DESC);

-- ── 2. SESSION CLEANUP TRIGGER FIX ──────────────────────────────────────────

-- The trg_cleanup_stale_sessions trigger runs on EVERY SELECT which is catastrophic
-- Remove it and replace with a scheduled function instead

-- First, find and drop the problematic trigger
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_trigger t
        JOIN pg_class c ON t.tgrelid = c.oid
        WHERE c.relname = 'user_sessions'
        AND t.tgname = 'trg_cleanup_stale_sessions'
    ) THEN
        EXECUTE 'DROP TRIGGER IF EXISTS trg_cleanup_stale_sessions ON user_sessions';
        RAISE NOTICE 'Dropped problematic trg_cleanup_stale_sessions trigger';
    END IF;
END $$;

-- Create a proper cleanup function that can be called via cron
CREATE OR REPLACE FUNCTION cleanup_stale_sessions(p_hours INT DEFAULT 24)
RETURNS INTEGER AS $$
DECLARE
    cleaned INTEGER;
BEGIN
    UPDATE user_sessions
    SET is_active = FALSE, logout_at = NOW()
    WHERE is_active = TRUE
      AND last_activity < NOW() - (p_hours || ' hours')::INTERVAL;
    GET DIAGNOSTICS cleaned = ROW_COUNT;
    RETURN cleaned;
END;
$$ LANGUAGE plpgsql;

-- ── 3. FULL-TEXT SEARCH FOR PRODUCTS ────────────────────────────────────────

-- Add tsvector column for full-text search
ALTER TABLE products ADD COLUMN IF NOT EXISTS search_vector tsvector;

-- Populate the search vector
UPDATE products SET 
    search_vector = to_tsvector('english', 
        coalesce(sku, '') || ' ' || 
        coalesce(name, '') || ' ' || 
        coalesce(category, '')
    );

-- Create index for full-text search
CREATE INDEX IF NOT EXISTS idx_products_search_vector ON products USING gin(search_vector);

-- Create trigger to maintain search vector
CREATE OR REPLACE FUNCTION trg_update_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := to_tsvector('english', 
        coalesce(NEW.sku, '') || ' ' || 
        coalesce(NEW.name, '') || ' ' || 
        coalesce(NEW.category, '')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_search_vector ON products;
CREATE TRIGGER trg_update_search_vector
    BEFORE INSERT OR UPDATE ON products
    FOR EACH ROW
    EXECUTE FUNCTION trg_update_search_vector();

-- ── 4. LOW STOCK INDEX ─────────────────────────────────────────────────────

-- Add index for low stock queries (CRITICAL for sp_product_low_stock)
CREATE INDEX IF NOT EXISTS idx_products_low_stock 
    ON products(current_stock, reorder_point, on_order) 
    WHERE current_stock <= reorder_point AND on_order <= 0;

-- ── 5. OPTIMIZED PRODUCT LIST FUNCTION ─────────────────────────────────────

-- Create optimized version of sp_product_list with full-text search support
CREATE OR REPLACE FUNCTION sp_product_list_optimized(
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
    -- Use full-text search for better performance
    RETURN QUERY
    WITH filtered AS (
        SELECT p.*, s.name AS supplier_name, s.tone AS supplier_tone, s.lead_days
        FROM products p
        LEFT JOIN suppliers s ON s.id = p.supplier_id
        WHERE (p_search = '' OR p.search_vector @@ plainto_tsquery('english', p_search))
          AND (p_category = '' OR p.category = ANY(string_to_array(p_category, ',')))
          AND (p_warehouse = '' OR p.warehouse = ANY(string_to_array(p_warehouse, ',')))
          AND (p_status = '' OR
               (p_status = 'ok' AND p.current_stock > p.reorder_point) OR
               (p_status = 'low' AND p.current_stock <= p.reorder_point AND p.current_stock > 0) OR
               (p_status = 'out' AND p.current_stock <= 0))
    )
    SELECT f.*, 
           (SELECT COUNT(*) FROM filtered) AS total_count
    FROM filtered f
    ORDER BY f.sku
    LIMIT p_limit OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;

-- ── 6. MATERIALIZED VIEWS FOR HEAVY QUERIES ─────────────────────────────────

-- (Removed mv_dashboard_metrics - dead object, never refreshed or queried)

-- ── 7. OPTIMIZED ETL FUNCTIONS ──────────────────────────────────────────────

-- Optimized SCD merge for products using MERGE (PostgreSQL 15+) or better approach
CREATE OR REPLACE FUNCTION etl_scd_merge_products_optimized()
RETURNS INTEGER AS $$
DECLARE
    v_total INTEGER := 0;
    v_temp  INTEGER;
BEGIN
    -- Use a temp table for better performance on large datasets
    CREATE TEMP TABLE temp_product_changes AS
    SELECT 
        p.id,
        p.sku,
        p.name,
        p.category,
        p.warehouse,
        p.supplier_id,
        p.unit_price,
        p.current_stock,
        p.reorder_point,
        MD5(ROW(p.sku, p.name, p.category, p.warehouse, p.supplier_id,
                p.unit_price, p.current_stock, p.reorder_point)::TEXT) AS new_hash
    FROM products p
    LEFT JOIN dim_product_scd scd ON scd.sku = p.sku AND scd.is_current = TRUE
    WHERE scd.sku IS NULL  -- New products
       OR scd.row_hash IS DISTINCT FROM MD5(ROW(p.sku, p.name, p.category, p.warehouse, p.supplier_id,
                                               p.unit_price, p.current_stock, p.reorder_point)::TEXT);

    -- Close old records for changed products
    UPDATE dim_product_scd scd
    SET valid_to = NOW(), is_current = FALSE
    FROM temp_product_changes tc
    WHERE scd.sku = tc.sku AND scd.is_current = TRUE
      AND scd.row_hash IS DISTINCT FROM tc.new_hash;

    GET DIAGNOSTICS v_temp = ROW_COUNT;
    v_total := v_total + v_temp;

    -- Insert new records
    INSERT INTO dim_product_scd (
        sku, product_name, category, warehouse, supplier_id,
        unit_price, current_stock, reorder_point, valid_from, is_current, row_hash
    )
    SELECT 
        tc.sku, tc.name, tc.category, tc.warehouse, tc.supplier_id,
        tc.unit_price, tc.current_stock, tc.reorder_point, NOW(), TRUE, tc.new_hash
    FROM temp_product_changes tc;

    GET DIAGNOSTICS v_temp = ROW_COUNT;
    v_total := v_total + v_temp;

    DROP TABLE temp_product_changes;
    RETURN v_total;
END;
$$ LANGUAGE plpgsql;

-- ── 8. FUNCTIONAL INDEXES FOR DATE QUERIES ─────────────────────────────────

-- Create functional index for date-based queries on movements
CREATE INDEX IF NOT EXISTS idx_movements_created_date ON movements((created_at::date));

-- ── 9. COMPOSITE INDEXES FOR COMMON QUERY PATTERNS ─────────────────────────

-- Index for dashboard queries that filter by stock status
CREATE INDEX IF NOT EXISTS idx_products_dashboard 
    ON products(current_stock, reorder_point, on_order, warehouse, category);

-- Index for supplier queries
CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers(name);

-- ── 10. SESSION INDEXES ─────────────────────────────────────────────────────

-- Improve session indexes
CREATE INDEX IF NOT EXISTS idx_user_sessions_active_user 
    ON user_sessions(user_id, is_active) 
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_user_sessions_token 
    ON user_sessions(session_token) 
    WHERE is_active = TRUE;

-- ── 11. ANALYZE TO UPDATE STATISTICS ──────────────────────────────────────

-- Update table statistics for query planner
ANALYZE products;
ANALYZE suppliers;
ANALYZE movements;
ANALYZE purchase_orders;
ANALYZE users;
ANALYZE user_sessions;
ANALYZE audit_log;

-- ── 12. INDEX USAGE MONITORING ─────────────────────────────────────────────

-- Create a function to check index usage
CREATE OR REPLACE FUNCTION check_index_usage()
RETURNS TABLE(
    table_name TEXT,
    index_name TEXT,
    index_scans BIGINT,
    index_tuples_read BIGINT,
    index_tuples_fetch BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        schemaname || '.' || tablename AS table_name,
        indexname AS index_name,
        idx_scan AS index_scans,
        idx_tup_read AS index_tuples_read,
        idx_tup_fetch AS index_tuples_fetch
    FROM pg_stat_user_indexes
    WHERE schemaname = 'public'
    ORDER BY idx_scan DESC;
END;
$$ LANGUAGE plpgsql;

-- ── END OF OPTIMIZATIONS ────────────────────────────────────────────────────