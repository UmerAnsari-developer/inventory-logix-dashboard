-- =============================================================================
-- InventoryLogix — PostgreSQL schema
-- Tables: users, suppliers, products, movements, audit_log, forecast_cache,
--          anomaly_log, purchase_orders
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(60) UNIQUE NOT NULL,
    email           VARCHAR(150) UNIQUE NOT NULL,
    password_hash   VARCHAR(256) NOT NULL,
    role            VARCHAR(20) NOT NULL DEFAULT 'viewer',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_login      TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT users_role_chk CHECK (role IN ('admin','manager','viewer'))
);

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

CREATE TABLE IF NOT EXISTS products (
    id              SERIAL PRIMARY KEY,
    sku             VARCHAR(50) UNIQUE NOT NULL,
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

CREATE TABLE IF NOT EXISTS movements (
    id              SERIAL PRIMARY KEY,
    product_id      INTEGER REFERENCES products(id) ON DELETE CASCADE,
    sku             VARCHAR(50),
    type            VARCHAR(20) NOT NULL,
    quantity        INTEGER NOT NULL,
    reference       VARCHAR(100),
    notes           TEXT,
    user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT movements_type_chk CHECK (type IN ('IN','OUT','ADJUSTMENT','RETURN'))
);

CREATE INDEX IF NOT EXISTS idx_movements_created_at ON movements(created_at);
CREATE INDEX IF NOT EXISTS idx_movements_type_created ON movements(type, created_at);
CREATE INDEX IF NOT EXISTS idx_movements_product_created ON movements(product_id, created_at);
CREATE INDEX IF NOT EXISTS idx_movements_product_type_created ON movements(product_id, type, created_at);

-- Products indexes for dashboard/reports queries
CREATE INDEX IF NOT EXISTS idx_products_stock_rop ON products(current_stock, reorder_point, on_order);
CREATE INDEX IF NOT EXISTS idx_products_warehouse_category ON products(warehouse, category);
CREATE INDEX IF NOT EXISTS idx_products_supplier ON products(supplier_id);
CREATE INDEX IF NOT EXISTS idx_products_unit_price ON products(unit_price);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id              SERIAL PRIMARY KEY,
    po_number       VARCHAR(40) UNIQUE NOT NULL,
    supplier_id     INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    product_id      INTEGER REFERENCES products(id) ON DELETE SET NULL,
    quantity        INTEGER NOT NULL,
    unit_cost       NUMERIC(12,2) DEFAULT 0,
    status          VARCHAR(20) NOT NULL DEFAULT 'draft',
    eta_date        DATE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT purchase_orders_status_chk
        CHECK (status IN ('draft','approved','in_transit','received','cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_po_supplier_status ON purchase_orders(supplier_id, status);
CREATE INDEX IF NOT EXISTS idx_po_created_at ON purchase_orders(created_at);
CREATE INDEX IF NOT EXISTS idx_po_product ON purchase_orders(product_id);

CREATE TABLE IF NOT EXISTS user_settings (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
    key             VARCHAR(80) NOT NULL,
    value           TEXT,
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT user_settings_user_key UNIQUE (user_id, key)
);

CREATE INDEX IF NOT EXISTS idx_user_settings_user ON user_settings(user_id);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      VARCHAR(256) NOT NULL UNIQUE,
    expires_at      TIMESTAMP NOT NULL,
    used            BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_password_reset_user ON password_reset_tokens(user_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
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

CREATE INDEX IF NOT EXISTS idx_products_sku          ON products(sku);
CREATE INDEX IF NOT EXISTS idx_products_category     ON products(category);
CREATE INDEX IF NOT EXISTS idx_movements_product     ON movements(product_id);
CREATE INDEX IF NOT EXISTS idx_movements_created     ON movements(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_user            ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_created         ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_forecast_product      ON forecast_cache(product_id);
CREATE INDEX IF NOT EXISTS idx_anomaly_product       ON anomaly_log(product_id);
CREATE INDEX IF NOT EXISTS idx_po_status             ON purchase_orders(status);

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

CREATE INDEX IF NOT EXISTS idx_fact_mov_date  ON fact_movement_daily(date_key);
CREATE INDEX IF NOT EXISTS idx_fact_mov_wh    ON fact_movement_daily(warehouse_key);
CREATE INDEX IF NOT EXISTS idx_fact_inv_date  ON fact_inventory_daily(date_key);
CREATE INDEX IF NOT EXISTS idx_fact_inv_wh    ON fact_inventory_daily(warehouse_key);

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

CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_token ON user_sessions(session_token);
CREATE INDEX IF NOT EXISTS idx_user_sessions_active ON user_sessions(is_active) WHERE is_active;

-- ETL pipeline bookkeeping (high-water mark for incremental runs).
CREATE TABLE IF NOT EXISTS etl_state (
    state_key       VARCHAR(60) PRIMARY KEY,
    value           TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
