-- Reports materialized view: pre-aggregates fact_movement_daily for fast reports
DROP MATERIALIZED VIEW IF EXISTS mv_daily_movement_summary;

CREATE MATERIALIZED VIEW mv_daily_movement_summary AS
SELECT 
    f.date_key,
    f.warehouse_key,
    dp.sku,
    dp.product_name,
    dp.category,
    ds.supplier_name,
    f.in_qty AS qty_in,
    f.out_qty AS qty_out,
    f.net_qty,
    f.in_qty - f.out_qty AS daily_net_qty
FROM fact_movement_daily f
JOIN dim_product dp ON dp.product_key = f.product_key
JOIN dim_supplier ds ON ds.supplier_id = dp.supplier_id;

-- Indexes for common report filters
CREATE INDEX idx_mv_dms_date ON mv_daily_movement_summary (date_key);
CREATE INDEX idx_mv_dms_sku ON mv_daily_movement_summary (sku);
CREATE INDEX idx_mv_dms_category ON mv_daily_movement_summary (category);
CREATE INDEX idx_mv_dms_supplier ON mv_daily_movement_summary (supplier_name);
CREATE INDEX idx_mv_dms_warehouse ON mv_daily_movement_summary (warehouse_key);

-- Unique index required for CONCURRENTLY refresh
CREATE UNIQUE INDEX idx_mv_dms_unique ON mv_daily_movement_summary (date_key, warehouse_key, sku);

-- Refresh function (called by ETL)
CREATE OR REPLACE FUNCTION sp_refresh_reports_mv()
RETURNS VOID AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_movement_summary;
END; $$ LANGUAGE plpgsql;