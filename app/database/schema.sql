-- =============================================================================
-- InventoryLogix — PostgreSQL schema
-- Tables: users, suppliers, products, movements, audit_log, forecast_cache,
--          anomaly_log, purchase_orders
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(60) UNIQUE NOT NULL,
    email           VARCHAR(150) UNIQUE NOT NULL,
    password_hash   VARCHAR(256),
    role            VARCHAR(20) NOT NULL DEFAULT 'viewer',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_login      TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    oauth_provider  VARCHAR(20),
    oauth_id        VARCHAR(200),
    CONSTRAINT users_role_chk CHECK (role IN ('admin','manager','viewer'))
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_provider VARCHAR(20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_id VARCHAR(200);
ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_oauth ON users(oauth_provider, oauth_id) WHERE oauth_provider IS NOT NULL;

-- ── RBAC role hierarchy + reporting relationship (additive, backward compatible) ──
-- users.role (admin/manager/viewer) stays the coarse permission tier;
-- job_role is the organizational hierarchy role (11 values).
ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(150);
ALTER TABLE users ADD COLUMN IF NOT EXISTS department VARCHAR(40);
ALTER TABLE users ADD COLUMN IF NOT EXISTS job_role VARCHAR(40);
ALTER TABLE users ADD COLUMN IF NOT EXISTS reporting_manager_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_users_reporting_manager ON users(reporting_manager_id);
CREATE INDEX IF NOT EXISTS idx_users_job_role ON users(job_role);

-- Hierarchy roles (10; "supplier" is documented but NOT seeded — the app has
-- no external-user support in its security model).
CREATE TABLE IF NOT EXISTS roles (
    job_role     VARCHAR(40) PRIMARY KEY,
    label        VARCHAR(80) NOT NULL,
    department   VARCHAR(40) NOT NULL,
    description  TEXT,
    sort_order   INTEGER NOT NULL DEFAULT 0
);

-- Seed hierarchy roles (industry-standard naming, 4-level structure)
INSERT INTO roles (job_role, label, department, sort_order) VALUES
    ('inventory_director',      'Inventory & Supply Chain Director', 'Leadership', 1),
    ('vp_operations',           'VP of Operations',                  'Leadership', 2),
    ('procurement_manager',     'Procurement Manager',               'Procurement', 3),
    ('warehouse_manager',       'Warehouse Operations Manager',      'Warehouse', 3),
    ('demand_planning_analyst', 'Demand Planning Analyst',           'Analytics', 3),
    ('procurement_buyer',       'Procurement Buyer',                 'Procurement', 4),
    ('procurement_coordinator', 'Procurement Coordinator',           'Procurement', 4),
    ('supplier_coordinator',    'Supplier Relationship Coordinator', 'Procurement', 4),
    ('receiving_associate',     'Receiving Associate',               'Warehouse', 4),
    ('inventory_analyst',       'Inventory Control Analyst',         'Warehouse', 4)
ON CONFLICT (job_role) DO UPDATE SET label = EXCLUDED.label,
    department = EXCLUDED.department, sort_order = EXCLUDED.sort_order;

-- NOTE: a legacy `role_permissions` table (permission → admin/manager/viewer
-- flags) already exists with a different shape; hierarchy mapping uses this
-- separate table to avoid conflicting with it.
CREATE TABLE IF NOT EXISTS job_role_permissions (
    job_role     VARCHAR(40) NOT NULL REFERENCES roles(job_role) ON DELETE CASCADE,
    permission   VARCHAR(60) NOT NULL,
    PRIMARY KEY (job_role, permission)
);

-- ── Report/task submissions (employee → reporting manager workflow) ──
CREATE TABLE IF NOT EXISTS reports (
    id                   SERIAL PRIMARY KEY,
    title                VARCHAR(200) NOT NULL,
    report_type          VARCHAR(40) NOT NULL DEFAULT 'general',
    description          TEXT,
    priority             VARCHAR(20) NOT NULL DEFAULT 'medium',
    related_module       VARCHAR(40),
    due_date             DATE,
    status               VARCHAR(20) NOT NULL DEFAULT 'submitted',
    submitted_by         INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    reporting_manager_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    submitted_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    reviewed_at          TIMESTAMP,
    review_comment       TEXT,
    CONSTRAINT reports_priority_chk CHECK (priority IN ('low','medium','high','critical')),
    CONSTRAINT reports_status_chk CHECK (status IN ('draft','submitted','under_review','approved','rejected','completed'))
);

CREATE INDEX IF NOT EXISTS idx_reports_submitted_by ON reports(submitted_by);
CREATE INDEX IF NOT EXISTS idx_reports_manager ON reports(reporting_manager_id);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);
CREATE INDEX IF NOT EXISTS idx_reports_submitted_at ON reports(submitted_at);

CREATE TABLE IF NOT EXISTS suppliers (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(150) NOT NULL,
    initials        VARCHAR(10),
    location        VARCHAR(200),
    lead_days       INTEGER DEFAULT 0,
    spend_amount    NUMERIC(12,2) DEFAULT 0,
    reliability     NUMERIC(5,2) DEFAULT 90.0,
    tone            VARCHAR(20) DEFAULT 'amber',
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS reliability NUMERIC(5,2) DEFAULT 90.0;
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;

CREATE TABLE IF NOT EXISTS products (
    id              SERIAL PRIMARY KEY,
    sku             VARCHAR(50) NOT NULL,
    name            VARCHAR(150) NOT NULL,
    category        VARCHAR(80),
    warehouse       VARCHAR(80) DEFAULT 'WH-Pune',
    current_stock   INTEGER NOT NULL DEFAULT 0,
    reorder_point   INTEGER NOT NULL DEFAULT 0,
    demand_rate     NUMERIC(12,2) DEFAULT 0,
    ordering_cost   NUMERIC(12,2) DEFAULT 0,
    holding_cost    NUMERIC(12,2) DEFAULT 0,
    unit_price      NUMERIC(12,2) DEFAULT 0,
    supplier_id     INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    on_order        INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE products ADD COLUMN IF NOT EXISTS warehouse VARCHAR(80) DEFAULT 'WH-Pune';
ALTER TABLE products ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;

CREATE TABLE IF NOT EXISTS movements (
    id              SERIAL PRIMARY KEY,
    product_id      INTEGER REFERENCES products(id) ON DELETE RESTRICT,
    type            VARCHAR(20) NOT NULL,
    quantity        INTEGER NOT NULL,
    reference       VARCHAR(100),
    notes           TEXT,
    user_id         INTEGER REFERENCES users(id) ON DELETE RESTRICT,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT movements_type_chk CHECK (type IN ('IN','OUT','ADJUSTMENT','RETURN'))
);

CREATE INDEX IF NOT EXISTS idx_movements_created_at ON movements(created_at);
CREATE INDEX IF NOT EXISTS idx_movements_type_created ON movements(type, created_at);
CREATE INDEX IF NOT EXISTS idx_movements_product_created ON movements(product_id, created_at);
CREATE INDEX IF NOT EXISTS idx_movements_product_type_created ON movements(product_id, type, created_at);

-- GAP-020 phase 1: soft delete for movements (mirrors migrations/20261012_soft_delete_ops
-- so bootstrap_database() matches the alembic path on fresh installs).
ALTER TABLE movements ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_movements_active
    ON movements (product_id, created_at) WHERE deleted_at IS NULL;

-- Products indexes for dashboard/reports queries
CREATE INDEX IF NOT EXISTS idx_products_stock_rop ON products(current_stock, reorder_point, on_order);
CREATE INDEX IF NOT EXISTS idx_products_warehouse_category ON products(warehouse, category);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_supplier ON products(supplier_id);

-- Fix DB-013: composite index matching sp_product_list's hot filter path.
-- Partial: soft-deleted rows never enter the index.
CREATE INDEX IF NOT EXISTS idx_products_list_filter
    ON products (warehouse, category, current_stock, reorder_point, on_order)
    WHERE deleted_at IS NULL;

-- Fix DB-001/DB-080: databases created before `sku UNIQUE` was added to CREATE TABLE
-- never received the constraint (bootstrap skips init_schema when tables exist).
-- DB-080: replace table-wide UNIQUE with partial index WHERE deleted_at IS NULL
-- so re-creating a deleted SKU is allowed. PG has no `ADD CONSTRAINT IF NOT EXISTS`,
-- so guard via pg_index and dedup live rows first.
DO $$
BEGIN
    -- Check if the partial index already exists
    IF to_regclass('products_sku_live_key') IS NULL THEN
        -- Dedup live rows only: keep lowest-id live row per SKU, rename later live duplicates.
        UPDATE products p
           SET sku = LEFT(p.sku, 44) || '#' || p.id
         WHERE p.deleted_at IS NULL
           AND EXISTS (
               SELECT 1 FROM products q
                WHERE q.sku = p.sku
                  AND q.deleted_at IS NULL
                  AND q.id < p.id);
        -- Create partial unique index (allows deleted SKUs to be reused)
        CREATE UNIQUE INDEX products_sku_live_key
            ON products (sku)
            WHERE deleted_at IS NULL;
        -- Drop the old full constraint if it exists (metadata-only, no scan)
        ALTER TABLE products DROP CONSTRAINT IF EXISTS products_sku_key;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS purchase_orders (
    id              SERIAL PRIMARY KEY,
    po_number       VARCHAR(40) UNIQUE NOT NULL,
    supplier_id     INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
    product_id      INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    quantity        INTEGER NOT NULL,
    unit_cost       NUMERIC(12,2) DEFAULT 0,
    status          VARCHAR(20) NOT NULL DEFAULT 'draft',
    eta_date        DATE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT purchase_orders_status_chk
        CHECK (status IN ('draft','approved','in_transit','received','cancelled')),
    CONSTRAINT chk_po_quantity_positive CHECK (quantity > 0),
    CONSTRAINT chk_po_unit_cost_nonnegative CHECK (unit_cost >= 0)
);

CREATE INDEX IF NOT EXISTS idx_po_created_at ON purchase_orders(created_at);
CREATE INDEX IF NOT EXISTS idx_po_product ON purchase_orders(product_id);

-- GAP-020 phase 1: soft delete for purchase orders (mirrors
-- migrations/20261012_soft_delete_ops — fresh-install parity).
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_po_active
    ON purchase_orders (status, created_at) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS user_settings (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
    key             VARCHAR(80) NOT NULL,
    value           TEXT,
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT user_settings_user_key UNIQUE (user_id, key)
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      VARCHAR(256) NOT NULL UNIQUE,
    expires_at      TIMESTAMP NOT NULL,
    used            BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_log (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER REFERENCES users(id) ON DELETE RESTRICT,
    action          VARCHAR(80) NOT NULL,
    target_type     VARCHAR(40),
    target_id       INTEGER,
    detail          JSONB,
    ip_address      VARCHAR(45),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS forecast_cache (
    id              SERIAL PRIMARY KEY,
    product_id      INTEGER REFERENCES products(id) ON DELETE CASCADE,
    model           VARCHAR(30) NOT NULL,
    horizon         INTEGER NOT NULL,
    payload         JSONB NOT NULL,
    accuracy        NUMERIC(5,2),
    generated_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS anomaly_log (
    id              SERIAL PRIMARY KEY,
    product_id      INTEGER REFERENCES products(id) ON DELETE CASCADE,
    anomaly_type    VARCHAR(40) NOT NULL,
    z_score         NUMERIC(8,3),
    confidence      NUMERIC(5,2),
    description     TEXT,
    detected_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_products_category     ON products(category);
CREATE INDEX IF NOT EXISTS idx_audit_user            ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_created         ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_forecast_product      ON forecast_cache(product_id);
CREATE INDEX IF NOT EXISTS idx_anomaly_product       ON anomaly_log(product_id);

-- Enhanced anomaly detection: structured business alerts
ALTER TABLE anomaly_log ADD COLUMN IF NOT EXISTS expected_value  NUMERIC(12,3);
ALTER TABLE anomaly_log ADD COLUMN IF NOT EXISTS observed_value  NUMERIC(12,3);
ALTER TABLE anomaly_log ADD COLUMN IF NOT EXISTS deviation_pct   NUMERIC(7,2);
ALTER TABLE anomaly_log ADD COLUMN IF NOT EXISTS metric          VARCHAR(40) DEFAULT 'quantity';
ALTER TABLE anomaly_log ADD COLUMN IF NOT EXISTS alert_date      DATE;
ALTER TABLE anomaly_log ADD COLUMN IF NOT EXISTS risk_level      VARCHAR(20) DEFAULT 'low';
ALTER TABLE anomaly_log ADD COLUMN IF NOT EXISTS detection_method VARCHAR(40) DEFAULT 'zscore';
ALTER TABLE anomaly_log ADD COLUMN IF NOT EXISTS recommended_action TEXT;
ALTER TABLE anomaly_log ADD COLUMN IF NOT EXISTS status          VARCHAR(20) DEFAULT 'new';
ALTER TABLE anomaly_log ADD COLUMN IF NOT EXISTS reviewed_at     TIMESTAMP;
ALTER TABLE anomaly_log ADD COLUMN IF NOT EXISTS reviewed_by     INTEGER REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE anomaly_log ADD COLUMN IF NOT EXISTS sku             VARCHAR(50);

-- Anomaly labeling fields (for precision/recall validation)
ALTER TABLE anomaly_log ADD COLUMN IF NOT EXISTS label           VARCHAR(20);
ALTER TABLE anomaly_log ADD COLUMN IF NOT EXISTS labeled_at      TIMESTAMP;
ALTER TABLE anomaly_log ADD COLUMN IF NOT EXISTS labeled_by      INTEGER REFERENCES users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_anomaly_status        ON anomaly_log(status);
CREATE INDEX IF NOT EXISTS idx_anomaly_risk          ON anomaly_log(risk_level);
CREATE INDEX IF NOT EXISTS idx_anomaly_alert_date    ON anomaly_log(alert_date);
CREATE INDEX IF NOT EXISTS idx_anomaly_label         ON anomaly_log(label) WHERE label IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_po_status             ON purchase_orders(status);

-- Fix DB-010: re-running anomaly detection must not duplicate alerts.
-- Expression index (nullable columns would defeat a plain unique index);
-- ON CONFLICT in AnomalyRepository.save targets the same expression list.
DELETE FROM anomaly_log a
 USING anomaly_log b
 WHERE a.id < b.id
   AND a.product_id IS NOT DISTINCT FROM b.product_id
   AND COALESCE(a.alert_date, a.detected_at::date) = COALESCE(b.alert_date, b.detected_at::date)
   AND a.anomaly_type = b.anomaly_type
   AND COALESCE(a.detection_method, 'zscore') = COALESCE(b.detection_method, 'zscore');
CREATE UNIQUE INDEX IF NOT EXISTS uq_anomaly_detection
    ON anomaly_log (product_id, COALESCE(alert_date, detected_at::date),
                    anomaly_type, COALESCE(detection_method, 'zscore'));

-- Fix DB-011: forecast_cache is a cache — keep one row per product/model/horizon.
DELETE FROM forecast_cache a
 USING forecast_cache b
 WHERE a.id < b.id
   AND a.product_id IS NOT DISTINCT FROM b.product_id
   AND a.model = b.model
   AND a.horizon = b.horizon;
CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_cache_key
    ON forecast_cache (product_id, model, horizon);

-- =============================================================================
-- Data warehouse — star schema
-- Built from the operational tables by the ETL (app/database/etl.py).
-- Dimensions are shared lookup tables; facts hold daily aggregates.
-- =============================================================================

CREATE TABLE IF NOT EXISTS dim_date (
    date_key        DATE PRIMARY KEY,
    year            SMALLINT NOT NULL,
    quarter         SMALLINT NOT NULL,
    month           SMALLINT NOT NULL,
    month_name      VARCHAR(12) NOT NULL,
    day_of_month    SMALLINT NOT NULL,
    day_of_week     SMALLINT NOT NULL,
    week            SMALLINT NOT NULL,
    is_weekend      BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_warehouse (
    warehouse_key   SERIAL PRIMARY KEY,
    warehouse_code  VARCHAR(12) UNIQUE NOT NULL,
    warehouse_name  VARCHAR(120) UNIQUE NOT NULL,
    city            VARCHAR(60),
    region          VARCHAR(40)
);

CREATE TABLE IF NOT EXISTS dim_product (
    product_key     SERIAL PRIMARY KEY,
    sku             VARCHAR(80) UNIQUE NOT NULL,
    product_name    VARCHAR(150) NOT NULL,
    category        VARCHAR(80),
    supplier_id     INTEGER,
    unit_price      NUMERIC(12,2)
);

CREATE TABLE IF NOT EXISTS dim_supplier (
    supplier_key    SERIAL PRIMARY KEY,
    supplier_id     INTEGER UNIQUE,
    supplier_name   VARCHAR(120) NOT NULL,
    location        VARCHAR(160),
    reliability     NUMERIC(5,2),
    lead_days       INTEGER
);

CREATE TABLE IF NOT EXISTS fact_movement_daily (
    date_key        DATE NOT NULL REFERENCES dim_date(date_key),
    warehouse_key   INTEGER NOT NULL REFERENCES dim_warehouse(warehouse_key),
    product_key     INTEGER NOT NULL REFERENCES dim_product(product_key),
    in_qty          INTEGER NOT NULL DEFAULT 0,
    out_qty         INTEGER NOT NULL DEFAULT 0,
    net_qty         INTEGER NOT NULL DEFAULT 0,
    in_value        NUMERIC(14,2) NOT NULL DEFAULT 0,
    out_value       NUMERIC(14,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (date_key, warehouse_key, product_key)
);

CREATE TABLE IF NOT EXISTS fact_inventory_daily (
    date_key        DATE NOT NULL REFERENCES dim_date(date_key),
    warehouse_key   INTEGER NOT NULL REFERENCES dim_warehouse(warehouse_key),
    product_key     INTEGER NOT NULL REFERENCES dim_product(product_key),
    stock_on_hand   NUMERIC(12,2) NOT NULL,
    reorder_point   NUMERIC(12,2) NOT NULL DEFAULT 0,
    inventory_value NUMERIC(14,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (date_key, warehouse_key, product_key)
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_token   VARCHAR(64) UNIQUE NOT NULL,
    ip_address      VARCHAR(45),
    user_agent      TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_activity   TIMESTAMP NOT NULL DEFAULT NOW(),
    login_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    logout_at       TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_sessions_active ON user_sessions(is_active) WHERE is_active;

-- ETL pipeline bookkeeping (high-water mark for incremental runs).
CREATE TABLE IF NOT EXISTS etl_state (
    state_key       VARCHAR(60) PRIMARY KEY,
    value           TEXT,
    updated_at      TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
);

-- Rate limiting state (PostgreSQL-backed, no Redis required)
CREATE TABLE IF NOT EXISTS rate_limit_state (
    id              SERIAL PRIMARY KEY,
    key             VARCHAR(255) NOT NULL UNIQUE,
    count           INTEGER NOT NULL DEFAULT 0,
    window_start    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_expires ON rate_limit_state(expires_at);
CREATE INDEX IF NOT EXISTS idx_rate_limit_key ON rate_limit_state(key);

-- ─────────────────────────────────────────────────────────────────
-- Forecast Model Monitoring
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS forecast_predictions (
    id                      SERIAL PRIMARY KEY,
    sku                     VARCHAR(50) NOT NULL,
    model_name              VARCHAR(30) NOT NULL,
    forecast_generated_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    forecast_date           DATE NOT NULL,
    predicted_value         NUMERIC(12,3) NOT NULL,
    actual_value            NUMERIC(12,3),
    forecast_horizon        INTEGER NOT NULL DEFAULT 1,
    status                  VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at              TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fp_sku_model_status_date
    ON forecast_predictions(sku, model_name, status, forecast_date);

-- Dedup: re-running a forecast must not accumulate duplicate prediction rows.
-- Keep the latest row per (sku, model_name, forecast_date), then enforce uniqueness
-- so actual_vs_predicted metrics are computed over distinct days, not run duplicates.
DELETE FROM forecast_predictions a
 USING forecast_predictions b
 WHERE a.id < b.id
   AND a.sku = b.sku
   AND a.model_name = b.model_name
   AND a.forecast_date = b.forecast_date;
CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_prediction
    ON forecast_predictions(sku, model_name, forecast_date);

CREATE TABLE IF NOT EXISTS forecast_monitoring_metrics (
    id                  SERIAL PRIMARY KEY,
    sku                 VARCHAR(50) NOT NULL,
    model_name          VARCHAR(30) NOT NULL,
    monitoring_date     DATE NOT NULL,
    aggregation_period  VARCHAR(10) NOT NULL DEFAULT 'daily',
    observation_count   INTEGER NOT NULL DEFAULT 0,
    mae                 NUMERIC(10,3),
    mape                NUMERIC(7,2),
    rmse                NUMERIC(10,3),
    mean_error          NUMERIC(10,3),
    error_std           NUMERIC(10,3),
    zero_demand_count   INTEGER NOT NULL DEFAULT 0,
    baseline_mae        NUMERIC(10,3),
    baseline_mape       NUMERIC(7,2),
    mae_change_percent  NUMERIC(7,2),
    mape_change_percent NUMERIC(7,2),
    model_status        VARCHAR(20) NOT NULL DEFAULT 'healthy',
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

-- WAPE (weighted absolute percentage error) — required metric for
-- intermittent demand; evaluate_all() now returns it.
ALTER TABLE forecast_monitoring_metrics ADD COLUMN IF NOT EXISTS wape NUMERIC(7,2);

CREATE INDEX IF NOT EXISTS idx_fmm_sku_model_date
    ON forecast_monitoring_metrics(sku, model_name, monitoring_date);

-- GAP-016: pinned per-model baselines (mirrors migrations/20261012_model_baselines
-- — fresh-install parity). baseline_metrics() reads this first, falling back to
-- the oldest evaluation window when a model has no pinned row.
CREATE TABLE IF NOT EXISTS model_baselines (
    id              SERIAL PRIMARY KEY,
    sku             VARCHAR NOT NULL,
    model_name      VARCHAR NOT NULL,
    mae             FLOAT,
    mape            FLOAT,
    source          VARCHAR NOT NULL DEFAULT 'promotion'
                    CHECK (source IN ('promotion','first_eval')),
    promoted_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    promoted_by     VARCHAR,
    CONSTRAINT model_baselines_sku_model UNIQUE (sku, model_name)
);

CREATE TABLE IF NOT EXISTS model_monitoring_alerts (
    id                  SERIAL PRIMARY KEY,
    sku                 VARCHAR(50) NOT NULL,
    model_name          VARCHAR(30) NOT NULL,
    alert_date          DATE NOT NULL,
    alert_type          VARCHAR(40) NOT NULL,
    severity            VARCHAR(20) NOT NULL DEFAULT 'warning',
    metric              VARCHAR(30) NOT NULL,
    baseline_value      NUMERIC(10,3),
    current_value       NUMERIC(10,3),
    change_percent      NUMERIC(7,2),
    message             TEXT,
    recommended_action  TEXT,
    status              VARCHAR(20) NOT NULL DEFAULT 'new',
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_monitoring_alert_dedup
    ON model_monitoring_alerts(sku, model_name, alert_type, alert_date);
CREATE INDEX IF NOT EXISTS idx_mma_sku_model_type_status
    ON model_monitoring_alerts(sku, model_name, alert_type, status);
CREATE INDEX IF NOT EXISTS idx_mma_created ON model_monitoring_alerts(created_at);

-- ─────────────────────────────────────────────────────────────────
-- Forecast Backtest Results
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS forecast_backtest_results (
    id                  BIGSERIAL PRIMARY KEY,
    product_id          INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    sku                 VARCHAR(50) NOT NULL,
    model_name          VARCHAR(30) NOT NULL,
    baseline_name       VARCHAR(30),
    origin_date         DATE NOT NULL,
    horizon             INTEGER NOT NULL,
    mae                 NUMERIC(10,3),
    mape                NUMERIC(7,2),
    rmse                NUMERIC(10,3),
    wape                NUMERIC(7,2),
    mase                NUMERIC(7,3),
    bias                NUMERIC(10,3),
    interval_coverage   NUMERIC(5,2),
    observation_count   INTEGER NOT NULL,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fbr_product_model_origin
    ON forecast_backtest_results(product_id, model_name, origin_date);
CREATE INDEX IF NOT EXISTS idx_fbr_sku_origin
    ON forecast_backtest_results(sku, origin_date);

-- ─────────────────────────────────────────────────────────────────
-- Anomaly Fatigue Metrics (Daily Aggregates)
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS anomaly_fatigue_daily (
    id                  SERIAL PRIMARY KEY,
    metric_date         DATE NOT NULL UNIQUE,
    total_alerts        INTEGER NOT NULL DEFAULT 0,
    critical_count      INTEGER NOT NULL DEFAULT 0,
    high_count          INTEGER NOT NULL DEFAULT 0,
    medium_count        INTEGER NOT NULL DEFAULT 0,
    low_count           INTEGER NOT NULL DEFAULT 0,
    reviewed_count      INTEGER NOT NULL DEFAULT 0,
    resolved_count      INTEGER NOT NULL DEFAULT 0,
    avg_resolve_hours   NUMERIC(6,2),
    review_rate         NUMERIC(5,2),
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_afd_date ON anomaly_fatigue_daily(metric_date);

-- ─────────────────────────────────────────────────────────────────
-- Notifications
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notifications (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    title           VARCHAR(200) NOT NULL,
    message         TEXT NOT NULL,
    icon            VARCHAR(10) DEFAULT '&#9675;',
    link            VARCHAR(300),
    is_read         BOOLEAN NOT NULL DEFAULT FALSE,
    dedup_key       VARCHAR(128),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notifications_user_read
    ON notifications(user_id, is_read, created_at DESC);
-- DB-069: existing DBs created `notifications` before dedup_key existed;
-- CREATE TABLE IF NOT EXISTS skips them, so guard the column add here.
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS dedup_key VARCHAR(128);
CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_user_dedup
    ON notifications(user_id, dedup_key) WHERE dedup_key IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────
-- Administration features + warehouses
-- Mirrors migrations/versions/20260920* so bootstrap_database()
-- (schema.sql path) matches the alembic path on fresh installs.
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS warehouses (
    id              SERIAL PRIMARY KEY,
    warehouse_name  VARCHAR(120) NOT NULL,
    location        VARCHAR(200),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS system_backups (
    id              SERIAL PRIMARY KEY,
    backup_name     VARCHAR(255) NOT NULL,
    backup_type     VARCHAR(50) NOT NULL,
    file_path       VARCHAR(500) NOT NULL,
    size            BIGINT,
    status          VARCHAR(50) NOT NULL DEFAULT 'success',
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    created_by      INTEGER NOT NULL REFERENCES users(id),
    deleted_at      TIMESTAMP,
    encrypted       BOOLEAN NOT NULL DEFAULT FALSE,
    encryption_key_id VARCHAR(100),
    checksum        VARCHAR(64)
);
CREATE INDEX IF NOT EXISTS idx_system_backups_created_at ON system_backups(created_at);
CREATE INDEX IF NOT EXISTS idx_system_backups_created_by ON system_backups(created_by);
CREATE INDEX IF NOT EXISTS idx_system_backups_deleted_at ON system_backups(deleted_at) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS system_config_overrides (
    id              SERIAL PRIMARY KEY,
    key             VARCHAR(80) NOT NULL UNIQUE,
    value           TEXT,
    description     TEXT,
    is_sensitive    BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_by      INTEGER NOT NULL REFERENCES users(id),
    deleted_at      TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_system_config_overrides_key ON system_config_overrides(key);
CREATE INDEX IF NOT EXISTS idx_system_config_overrides_updated_at ON system_config_overrides(updated_at);
CREATE INDEX IF NOT EXISTS idx_system_config_overrides_deleted_at ON system_config_overrides(deleted_at) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS scheduled_audit_reports (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    format          VARCHAR(10) NOT NULL,
    frequency       VARCHAR(20) NOT NULL,
    parameters      JSON,
    next_run_time   TIMESTAMP,
    last_run_time   TIMESTAMP,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    created_by      INTEGER NOT NULL REFERENCES users(id),
    updated_by      INTEGER NOT NULL REFERENCES users(id),
    deleted_at      TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_scheduled_audit_reports_next_run ON scheduled_audit_reports(next_run_time);
CREATE INDEX IF NOT EXISTS idx_scheduled_audit_reports_active ON scheduled_audit_reports(is_active);
CREATE INDEX IF NOT EXISTS idx_scheduled_audit_reports_deleted_at ON scheduled_audit_reports(deleted_at) WHERE deleted_at IS NULL;

-- Ensure is_active default is applied on existing tables
ALTER TABLE scheduled_audit_reports ALTER COLUMN is_active SET DEFAULT TRUE;

-- Idempotency keys for safe retry of write operations
CREATE TABLE IF NOT EXISTS idempotency_keys (
    id              BIGSERIAL PRIMARY KEY,
    key             VARCHAR(128) NOT NULL,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    response_json   JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_idempotency_key_user ON idempotency_keys(key, user_id);
CREATE INDEX IF NOT EXISTS idx_idempotency_keys_user_created ON idempotency_keys(user_id, created_at);

-- Performance indexes (same set as migrations/versions/20260922_optimizations.py)
CREATE INDEX IF NOT EXISTS idx_products_supplier_id ON products(supplier_id);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_supplier_id ON purchase_orders(supplier_id);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_product_id ON purchase_orders(product_id);

-- ─────────────────────────────────────────────────────────────────
-- Row-Level Security: enable on every table with NO policies.
-- Supabase exposes all tables via its auto-generated REST API
-- (PostgREST); with RLS disabled, anyone holding the project URL
-- can read/modify all data — including users.password_hash and
-- password_reset_tokens. With RLS enabled and zero policies, the
-- public API is deny-by-default for every role except table owners.
-- The Flask app connects as the table owner (postgres), which
-- bypasses RLS, so the application is unaffected.
-- ─────────────────────────────────────────────────────────────────
DO $$
DECLARE
    t TEXT;
BEGIN
    FOR t IN
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename NOT LIKE 'pg_%'
          AND tablename NOT LIKE 'schema_%'
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    END LOOP;
END $$;

-- ═══════════════════════════════════════════════════════════════════════════
-- Integrity audit additions (idempotent — safe on fresh AND existing DBs)
-- ═══════════════════════════════════════════════════════════════════════════

-- Check constraints for products
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'products' AND constraint_name = 'chk_current_stock_nonnegative'
    ) THEN
        ALTER TABLE products ADD CONSTRAINT chk_current_stock_nonnegative CHECK (current_stock >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'products' AND constraint_name = 'chk_reorder_point_nonnegative'
    ) THEN
        ALTER TABLE products ADD CONSTRAINT chk_reorder_point_nonnegative CHECK (reorder_point >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'products' AND constraint_name = 'chk_demand_rate_nonnegative'
    ) THEN
        ALTER TABLE products ADD CONSTRAINT chk_demand_rate_nonnegative CHECK (demand_rate >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'products' AND constraint_name = 'chk_ordering_cost_nonnegative'
    ) THEN
        ALTER TABLE products ADD CONSTRAINT chk_ordering_cost_nonnegative CHECK (ordering_cost >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'products' AND constraint_name = 'chk_holding_cost_nonnegative'
    ) THEN
        ALTER TABLE products ADD CONSTRAINT chk_holding_cost_nonnegative CHECK (holding_cost >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'products' AND constraint_name = 'chk_unit_price_nonnegative'
    ) THEN
        ALTER TABLE products ADD CONSTRAINT chk_unit_price_nonnegative CHECK (unit_price >= 0);
    END IF;
END $$;

-- Check constraints for suppliers
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'suppliers' AND constraint_name = 'chk_lead_days_nonnegative'
    ) THEN
        ALTER TABLE suppliers ADD CONSTRAINT chk_lead_days_nonnegative CHECK (lead_days >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'suppliers' AND constraint_name = 'chk_spend_amount_nonnegative'
    ) THEN
        ALTER TABLE suppliers ADD CONSTRAINT chk_spend_amount_nonnegative CHECK (spend_amount >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'suppliers' AND constraint_name = 'chk_reliability_range'
    ) THEN
        ALTER TABLE suppliers ADD CONSTRAINT chk_reliability_range CHECK (reliability BETWEEN 0 AND 100);
    END IF;
END $$;

-- Check constraint for movements
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'movements' AND constraint_name = 'chk_quantity_positive'
    ) THEN
        ALTER TABLE movements ADD CONSTRAINT chk_quantity_positive CHECK (quantity > 0);
    END IF;
END $$;

-- DB-002: remove redundant sku column from movements (no-op on fresh DBs)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'movements' AND column_name = 'sku'
    ) THEN
        ALTER TABLE movements DROP COLUMN sku;
    END IF;
END $$;
DROP INDEX IF EXISTS idx_movements_sku;

-- Unique constraints (duplicate rows must be cleaned before applying manually)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'uq_scheduled_audit_reports_name'
    ) THEN
        ALTER TABLE scheduled_audit_reports ADD CONSTRAINT uq_scheduled_audit_reports_name UNIQUE (name);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'uq_warehouses_warehouse_name'
    ) THEN
        ALTER TABLE warehouses ADD CONSTRAINT uq_warehouses_warehouse_name UNIQUE (warehouse_name);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'uq_system_backups_backup_name'
    ) THEN
        ALTER TABLE system_backups ADD CONSTRAINT uq_system_backups_backup_name UNIQUE (backup_name);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_model_monitoring_alerts_alert_date ON model_monitoring_alerts(alert_date);
