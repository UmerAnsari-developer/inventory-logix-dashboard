-- =============================================================================
-- InventoryLogix — Data Warehouse Schema (Enhanced)
-- SCD Type 2 dimensions, audit facts, session facts, login tracking
-- =============================================================================

-- ── SCD TYPE 2: PRODUCT DIMENSION ────────────────────────────────────────────
-- Tracks full history of product attribute changes

CREATE TABLE IF NOT EXISTS dim_product_scd (
    product_key     SERIAL PRIMARY KEY,
    sku             VARCHAR(80) NOT NULL,
    product_name    VARCHAR(150) NOT NULL,
    category        VARCHAR(80),
    warehouse       VARCHAR(80),
    supplier_id     INTEGER,
    unit_price      NUMERIC(12,2),
    current_stock   INTEGER,
    reorder_point   INTEGER,
    valid_from      TIMESTAMP NOT NULL DEFAULT NOW(),
    valid_to        TIMESTAMP,
    is_current      BOOLEAN NOT NULL DEFAULT TRUE,
    row_hash        VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_scd_product_sku ON dim_product_scd(sku);
CREATE INDEX IF NOT EXISTS idx_scd_product_current ON dim_product_scd(is_current) WHERE is_current;
CREATE INDEX IF NOT EXISTS idx_scd_product_hash ON dim_product_scd(row_hash);

-- ── SCD TYPE 2: SUPPLIER DIMENSION ──────────────────────────────────────────
-- Tracks reliability, lead_days, spend changes over time

CREATE TABLE IF NOT EXISTS dim_supplier_scd (
    supplier_key    SERIAL PRIMARY KEY,
    supplier_id     INTEGER NOT NULL,
    supplier_name   VARCHAR(120) NOT NULL,
    location        VARCHAR(160),
    reliability     NUMERIC(5,2),
    lead_days       INTEGER,
    spend_amount    NUMERIC(12,2),
    valid_from      TIMESTAMP NOT NULL DEFAULT NOW(),
    valid_to        TIMESTAMP,
    is_current      BOOLEAN NOT NULL DEFAULT TRUE,
    row_hash        VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_scd_supplier_id ON dim_supplier_scd(supplier_id);
CREATE INDEX IF NOT EXISTS idx_scd_supplier_current ON dim_supplier_scd(is_current) WHERE is_current;

-- ── SCD TYPE 2: WAREHOUSE DIMENSION ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS dim_warehouse_scd (
    warehouse_key   SERIAL PRIMARY KEY,
    warehouse_code  VARCHAR(12) NOT NULL,
    warehouse_name  VARCHAR(120) NOT NULL,
    city            VARCHAR(60),
    region          VARCHAR(40),
    valid_from      TIMESTAMP NOT NULL DEFAULT NOW(),
    valid_to        TIMESTAMP,
    is_current      BOOLEAN NOT NULL DEFAULT TRUE,
    row_hash        VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_scd_warehouse_code ON dim_warehouse_scd(warehouse_code);
CREATE INDEX IF NOT EXISTS idx_scd_warehouse_current ON dim_warehouse_scd(is_current) WHERE is_current;

-- ── USER DIMENSION (SCD Type 2) ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS dim_user (
    user_key        SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL,
    username        VARCHAR(60) NOT NULL,
    email           VARCHAR(150),
    role            VARCHAR(20),
    oauth_provider  VARCHAR(20),
    is_active       BOOLEAN,
    valid_from      TIMESTAMP NOT NULL DEFAULT NOW(),
    valid_to        TIMESTAMP,
    is_current      BOOLEAN NOT NULL DEFAULT TRUE,
    row_hash        VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_dim_user_id ON dim_user(user_id);
CREATE INDEX IF NOT EXISTS idx_dim_user_current ON dim_user(is_current) WHERE is_current;

-- ── FACT: LOGIN EVENTS ──────────────────────────────────────────────────────
-- Every login attempt (success + failure) tracked for security analytics

CREATE TABLE IF NOT EXISTS fact_login_events (
    event_id        SERIAL PRIMARY KEY,
    user_key        INTEGER REFERENCES dim_user(user_key),
    login_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    ip_address      VARCHAR(45),
    user_agent      TEXT,
    login_method    VARCHAR(20) NOT NULL DEFAULT 'password',
    success         BOOLEAN NOT NULL DEFAULT TRUE,
    failure_reason  VARCHAR(80),
    session_token   VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_login_user ON fact_login_events(user_key);
CREATE INDEX IF NOT EXISTS idx_login_time ON fact_login_events(login_at);
CREATE INDEX IF NOT EXISTS idx_login_success ON fact_login_events(success);

-- ── FACT: SESSION ACTIVITY ───────────────────────────────────────────────────
-- Granular session tracking: who logged in, when, from where, duration

CREATE TABLE IF NOT EXISTS fact_session_activity (
    session_key     SERIAL PRIMARY KEY,
    user_key        INTEGER REFERENCES dim_user(user_key),
    session_token   VARCHAR(64) UNIQUE NOT NULL,
    login_at        TIMESTAMP NOT NULL,
    logout_at       TIMESTAMP,
    last_activity   TIMESTAMP,
    duration_sec    INTEGER GENERATED ALWAYS AS (
        CASE WHEN logout_at IS NOT NULL
             THEN EXTRACT(EPOCH FROM (logout_at - login_at))::INTEGER
             ELSE NULL END
    ) STORED,
    ip_address      VARCHAR(45),
    user_agent      TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_session_user ON fact_session_activity(user_key);
CREATE INDEX IF NOT EXISTS idx_session_time ON fact_session_activity(login_at);
CREATE INDEX IF NOT EXISTS idx_session_active ON fact_session_activity(is_active) WHERE is_active;

-- ── FACT: SIGNUP EVENTS ─────────────────────────────────────────────────────
-- Track new user registrations

CREATE TABLE IF NOT EXISTS fact_signup_events (
    event_id        SERIAL PRIMARY KEY,
    user_key        INTEGER REFERENCES dim_user(user_key),
    signup_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    ip_address      VARCHAR(45),
    signup_method   VARCHAR(20) NOT NULL DEFAULT 'form',
    oauth_provider  VARCHAR(20),
    success         BOOLEAN NOT NULL DEFAULT TRUE,
    failure_reason  VARCHAR(80)
);

CREATE INDEX IF NOT EXISTS idx_signup_time ON fact_signup_events(signup_at);
CREATE INDEX IF NOT EXISTS idx_signup_method ON fact_signup_events(signup_method);

-- ── FACT: AUDIT ACTIVITY (Daily Aggregate) ───────────────────────────────────
-- Pre-aggregated audit data for fast reporting

CREATE TABLE IF NOT EXISTS fact_audit_daily (
    date_key        DATE NOT NULL REFERENCES dim_date(date_key),
    action          VARCHAR(80) NOT NULL,
    target_type     VARCHAR(40),
    user_key        INTEGER REFERENCES dim_user(user_key),
    event_count     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date_key, action, target_type, user_key)
);

CREATE INDEX IF NOT EXISTS idx_audit_daily_date ON fact_audit_daily(date_key);

-- ── FACT: PRODUCT ACTIVITY DAILY ─────────────────────────────────────────────
-- Daily aggregated product movement stats per warehouse

CREATE TABLE IF NOT EXISTS fact_product_daily (
    date_key        DATE NOT NULL REFERENCES dim_date(date_key),
    product_key     INTEGER REFERENCES dim_product(product_key),
    warehouse_key   INTEGER REFERENCES dim_warehouse(warehouse_key),
    in_qty          INTEGER NOT NULL DEFAULT 0,
    out_qty         INTEGER NOT NULL DEFAULT 0,
    net_qty         INTEGER NOT NULL DEFAULT 0,
    in_value        NUMERIC(14,2) NOT NULL DEFAULT 0,
    out_value       NUMERIC(14,2) NOT NULL DEFAULT 0,
    stock_on_hand   NUMERIC(12,2) NOT NULL DEFAULT 0,
    reorder_point   NUMERIC(12,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (date_key, product_key, warehouse_key)
);

CREATE INDEX IF NOT EXISTS idx_product_daily_date ON fact_product_daily(date_key);

-- ── ETL STATE (Extended) ────────────────────────────────────────────────────
-- Track ETL state for warehouse operations

CREATE TABLE IF NOT EXISTS etl_warehouse_state (
    state_key       VARCHAR(60) PRIMARY KEY,
    value           TEXT,
    updated_at      TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
);
