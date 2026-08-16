-- =============================================================================
-- InventoryLogix — PostgreSQL schema for Render
-- -----------------------------------------------------------------------------
-- How to use:
--   1. Create a PostgreSQL database on Render (free tier is fine).
--   2. Open the Render PostgreSQL "Connect" panel → copy the "PSQL command".
--   3. Paste the file into the psql shell with:  \i database.sql
--      (or paste the whole file into the psql console and press Enter).
--   4. Point DATABASE_URL / DB_* env vars at the Render database.
--
-- This script DROPS and recreates all tables, so it is safe to re-run.
-- Demo users are inserted idempotently (ON CONFLICT DO NOTHING) with real
-- Werkzeug scrypt hashes so the documented demo credentials work out of the box.
-- =============================================================================

-- Drop in dependency order (children first).
DROP TABLE IF EXISTS fact_inventory_daily CASCADE;
DROP TABLE IF EXISTS fact_movement_daily  CASCADE;
DROP TABLE IF EXISTS dim_supplier         CASCADE;
DROP TABLE IF EXISTS dim_product          CASCADE;
DROP TABLE IF EXISTS dim_warehouse        CASCADE;
DROP TABLE IF EXISTS dim_date             CASCADE;
DROP TABLE IF EXISTS etl_state            CASCADE;
DROP TABLE IF EXISTS anomaly_log          CASCADE;
DROP TABLE IF EXISTS forecast_cache       CASCADE;
DROP TABLE IF EXISTS audit_log            CASCADE;
DROP TABLE IF EXISTS password_reset_tokens CASCADE;
DROP TABLE IF EXISTS user_settings        CASCADE;
DROP TABLE IF EXISTS purchase_orders      CASCADE;
DROP TABLE IF EXISTS movements            CASCADE;
DROP TABLE IF EXISTS products             CASCADE;
DROP TABLE IF EXISTS suppliers            CASCADE;
DROP TABLE IF EXISTS users                CASCADE;

-- =============================================================================
-- Operational tables
-- =============================================================================

CREATE TABLE users (
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

CREATE TABLE suppliers (
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

CREATE TABLE products (
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

CREATE TABLE movements (
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

CREATE TABLE purchase_orders (
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

CREATE TABLE user_settings (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
    key             VARCHAR(80) NOT NULL,
    value           TEXT,
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT user_settings_user_key UNIQUE (user_id, key)
);

CREATE INDEX idx_user_settings_user ON user_settings(user_id);

CREATE TABLE password_reset_tokens (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      VARCHAR(256) NOT NULL UNIQUE,
    expires_at      TIMESTAMP NOT NULL,
    used            BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_password_reset_user ON password_reset_tokens(user_id);

CREATE TABLE audit_log (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action          VARCHAR(80) NOT NULL,
    target_type     VARCHAR(40),
    target_id       INTEGER,
    detail          JSONB,
    ip_address      VARCHAR(45),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE forecast_cache (
    id              SERIAL PRIMARY KEY,
    product_id      INTEGER REFERENCES products(id) ON DELETE CASCADE,
    model           VARCHAR(30) NOT NULL,
    horizon         INTEGER NOT NULL,
    payload         JSONB NOT NULL,
    accuracy        NUMERIC(5,2),
    generated_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE anomaly_log (
    id              SERIAL PRIMARY KEY,
    product_id      INTEGER REFERENCES products(id) ON DELETE CASCADE,
    anomaly_type    VARCHAR(40) NOT NULL,
    z_score         NUMERIC(8,3),
    confidence      NUMERIC(5,2),
    description     TEXT,
    detected_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Operational indexes
CREATE INDEX idx_products_sku          ON products(sku);
CREATE INDEX idx_products_category     ON products(category);
CREATE INDEX idx_movements_product     ON movements(product_id);
CREATE INDEX idx_movements_created     ON movements(created_at);
CREATE INDEX idx_audit_user            ON audit_log(user_id);
CREATE INDEX idx_audit_created         ON audit_log(created_at);
CREATE INDEX idx_forecast_product      ON forecast_cache(product_id);
CREATE INDEX idx_anomaly_product       ON anomaly_log(product_id);
CREATE INDEX idx_po_status             ON purchase_orders(status);

-- =============================================================================
-- Data warehouse — star schema (built by the ETL)
-- =============================================================================

CREATE TABLE dim_date (
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

CREATE TABLE dim_warehouse (
    warehouse_key   SERIAL PRIMARY KEY,
    warehouse_code  VARCHAR(12) UNIQUE NOT NULL,
    warehouse_name  VARCHAR(120) UNIQUE NOT NULL,
    city            VARCHAR(60),
    region          VARCHAR(40)
);

CREATE TABLE dim_product (
    product_key     SERIAL PRIMARY KEY,
    sku             VARCHAR(80) UNIQUE NOT NULL,
    product_name    VARCHAR(150) NOT NULL,
    category        VARCHAR(80),
    supplier_id     INTEGER,
    unit_price      NUMERIC(12,2)
);

CREATE TABLE dim_supplier (
    supplier_key    SERIAL PRIMARY KEY,
    supplier_id     INTEGER UNIQUE,
    supplier_name   VARCHAR(120) NOT NULL,
    location        VARCHAR(160),
    reliability     NUMERIC(5,2),
    lead_days       INTEGER
);

CREATE TABLE fact_movement_daily (
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

CREATE TABLE fact_inventory_daily (
    date_key        DATE NOT NULL REFERENCES dim_date(date_key),
    warehouse_key   INTEGER NOT NULL REFERENCES dim_warehouse(warehouse_key),
    product_key     INTEGER NOT NULL REFERENCES dim_product(product_key),
    stock_on_hand   NUMERIC(12,2) NOT NULL,
    reorder_point   NUMERIC(12,2) NOT NULL DEFAULT 0,
    inventory_value NUMERIC(14,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (date_key, warehouse_key, product_key)
);

CREATE INDEX idx_fact_mov_date  ON fact_movement_daily(date_key);
CREATE INDEX idx_fact_mov_wh    ON fact_movement_daily(warehouse_key);
CREATE INDEX idx_fact_inv_date  ON fact_inventory_daily(date_key);
CREATE INDEX idx_fact_inv_wh    ON fact_inventory_daily(warehouse_key);

-- ETL pipeline bookkeeping (high-water mark for incremental runs).
CREATE TABLE etl_state (
    key         VARCHAR(60) PRIMARY KEY,
    value       TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- Demo users — idempotent inserts with real Werkzeug scrypt hashes.
-- Credentials (documented in README):
--   admin   / Admin@123
--   manager / Manager@123
--   viewer  / Viewer@123
-- Self-registration always creates a viewer account; write access is
-- restricted to admin/manager by the application.
-- =============================================================================

INSERT INTO users (username, email, password_hash, role) VALUES
    ('admin',   'admin@inventorylogix.local',
     'scrypt:32768:8:1$Q0eu7tfipRd94i6p$e573aef3eb6352fd0191708b2bd3b93efa86e19b36e276e7960479354c5c514e350dbe71ec7017517dd137263aca230be02c2d69ec260a5d3544ef8036768024',
     'admin'),
    ('manager', 'manager@inventorylogix.local',
     'scrypt:32768:8:1$NWxHUQAzVHuvluT0$813c13a34915c563541eb70934202419e6c915468257b37effce85be21fbae242cfbdc3df1b803592042979b0bb084db9ed524fdbb64688807fd11fca03f19d4',
     'manager'),
    ('viewer',  'viewer@inventorylogix.local',
     'scrypt:32768:8:1$LLRgFOGDMNOKJkTE$d6f671ad35413b1e8c7d0650f309a0a891092aaa52af8dbadc59305cb566437bb8c01b940d2d620a6c1061ae3936de4ac5509aeb34244fa295679379b94af826',
     'viewer')
ON CONFLICT (username) DO NOTHING;

-- =============================================================================
-- Done. Optional next step: run the DataCo dataset seeder from the app
-- (flask --app run.py seed-db --force) to populate products and suppliers.
-- =============================================================================