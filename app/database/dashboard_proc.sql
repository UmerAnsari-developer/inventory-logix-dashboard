-- Dashboard single proc: replaces 11 sequential queries
CREATE OR REPLACE FUNCTION sp_dashboard_snapshot()
RETURNS TABLE(metric TEXT, value BIGINT) AS $$
BEGIN
    RETURN QUERY SELECT 'total_users', COUNT(*) FROM users;
    RETURN QUERY SELECT 'active_users_30d', COUNT(*) 
        FROM users WHERE last_login >= NOW() - INTERVAL '30 days';
    RETURN QUERY SELECT 'total_products', COUNT(*) 
        FROM products WHERE deleted_at IS NULL;
    RETURN QUERY SELECT 'low_stock_products', COUNT(*) 
        FROM products WHERE current_stock <= reorder_point AND deleted_at IS NULL;
    RETURN QUERY SELECT 'total_suppliers', COUNT(*) 
        FROM suppliers WHERE deleted_at IS NULL;
    RETURN QUERY SELECT 'total_movements', COUNT(*) 
        FROM movements WHERE deleted_at IS NULL;
    RETURN QUERY SELECT 'open_purchase_orders', COUNT(*) 
        FROM purchase_orders 
        WHERE status IN ('draft','approved','ordered') AND deleted_at IS NULL;
    RETURN QUERY SELECT 'pending_receipts', COUNT(*) 
        FROM goods_receipts gr
        JOIN purchase_orders po ON po.id = gr.po_id
        WHERE po.status = 'ordered' AND po.deleted_at IS NULL;
    RETURN QUERY SELECT 'last_etl_run', EXTRACT(EPOCH FROM etl_state.value::TIMESTAMP)::BIGINT
        FROM etl_state WHERE state_key = 'last_run_at';
END; $$ LANGUAGE plpgsql;