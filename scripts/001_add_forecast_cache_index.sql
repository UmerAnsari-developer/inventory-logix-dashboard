-- Migration: indexes backing the in-memory/DB forecast cache lookups.
-- The app also defines these in app/database/schema.sql (IF NOT EXISTS), so
-- they are re-applied automatically on startup for any database.
-- Run with: psql -U <user> -d <db> -f 001_add_forecast_cache_index.sql

-- Fast exact-key lookup used by ForecastRepository.recent_for()
-- (product_id, model, horizon) — the forecast cache-aside key.
CREATE INDEX IF NOT EXISTS idx_forecast_cache_lookup
    ON forecast_cache (product_id, model, horizon);

-- Product-level anomaly log lookup
CREATE INDEX IF NOT EXISTS idx_anomaly_log_product_id
    ON anomaly_log (product_id);
