"""Environment-based configuration classes."""
from __future__ import annotations

import os
from datetime import timedelta


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _require_env(name: str) -> str:
    """Raise on startup if a critical env var is missing."""
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Required environment variable {name} is not set. Add it to your .env file.")
    return val


class Config:
    """Base configuration loaded from environment variables."""

    # DB-013/DB-075 (Timezone/UTC): all DB timestamps are UTC — the connection
    # pins TimeZone=UTC via libpq options (app/database/connection.py). Naive
    # TIMESTAMP columns store UTC wall-clock values; app code must use
    # timezone-aware UTC (datetime.now(timezone.utc)) for comparisons against
    # TIMESTAMPTZ columns (rate_limit_state) and naive UTC for TIMESTAMP columns.

    SECRET_KEY = os.environ.get("SECRET_KEY") or _require_env("SECRET_KEY")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool(os.environ.get("SESSION_COOKIE_SECURE"), True)

    # Admin session timeout (shorter than regular session for security)
    ADMIN_SESSION_TIMEOUT_MINUTES = int(os.environ.get("ADMIN_SESSION_TIMEOUT_MINUTES", "30"))

    WTF_CSRF_TIME_LIMIT = 60 * 60 * 8
    WTF_CSRF_ENABLED = True

    # Upload size limit (CSV import, etc.). Flask rejects larger bodies with
    # 413 before the bytes are read into memory. Default 5 MB.
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH_MB", "5")) * 1024 * 1024

    # Database
    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_PORT = int(os.environ.get("DB_PORT", "5432"))
    DB_NAME = os.environ.get("DB_NAME", "inventory_db")
    DB_USER = os.environ.get("DB_USER", "postgres")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
    DB_SSLMODE = os.environ.get("DB_SSLMODE", "")
    DATABASE_URL = os.environ.get("DATABASE_URL")

    # SMTP — used to deliver password-reset emails. When no SMTP host is set
    # the reset link is surfaced in the UI instead (development fallback).
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    MAIL_FROM = os.environ.get("MAIL_FROM", "no-reply@inventorylogix.local")
    MAIL_USE_TLS = _bool(os.environ.get("MAIL_USE_TLS"), True)
    PASSWORD_RESET_TTL_MINUTES = int(os.environ.get("PASSWORD_RESET_TTL_MINUTES", "5"))

    # SendGrid API (HTTPS) — works on platforms that block outbound SMTP (e.g. Render free tier)
    SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")

    # Rate limiting (flask-limiter) storage backend — memory:// default;
    # For multi-worker deployments, set RATELIMIT_STORAGE_URI to redis://... or postgresql://...
    # (requires flask-limiter-postgres package for PostgreSQL).
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    # Opt-in reverse-proxy trust (Render etc.). When truthy the factory
    # installs ProxyFix so the limiter keys on the X-Forwarded-For client
    # hop instead of the shared proxy IP. Default OFF keeps XFF
    # spoof-proof when the app is directly exposed.
    TRUST_PROXY = _bool(os.environ.get("TRUST_PROXY"))

    # Anomaly detection thresholds (used by anomaly.py)
    ANOMALY_ZWARNING = float(os.environ.get("ANOMALY_ZWARNING", "2.0"))
    ANOMALY_ZHIGH = float(os.environ.get("ANOMALY_ZHIGH", "3.0"))
    ANOMALY_ZCRITICAL = float(os.environ.get("ANOMALY_ZCRITICAL", "4.0"))
    ANOMALY_CONTAMINATION = float(os.environ.get("ANOMALY_CONTAMINATION", "0.05"))
    ANOMALY_RULE_MULTIPLIER = float(os.environ.get("ANOMALY_RULE_MULTIPLIER", "3.0"))
    ANOMALY_FORECAST_DEVIATION = float(os.environ.get("ANOMALY_FORECAST_DEVIATION", "0.40"))

    # Model monitoring thresholds
    MODEL_WARNING_THRESHOLD = float(os.environ.get("MODEL_WARNING_THRESHOLD", "10"))
    MODEL_DEGRADATION_THRESHOLD = float(os.environ.get("MODEL_DEGRADATION_THRESHOLD", "25"))
    MODEL_CRITICAL_THRESHOLD = float(os.environ.get("MODEL_CRITICAL_THRESHOLD", "50"))
    MODEL_MONITORING_WINDOW = int(os.environ.get("MODEL_MONITORING_WINDOW", "7"))

    # Bootstrap behaviour. ``RUN_ETL_ON_STARTUP`` lets deployments skip the
    # (potentially slow, remote) star-schema rebuild on every boot when the
    # warehouse is already populated. Defaults to True for safety.
    RUN_ETL_ON_STARTUP = _bool(os.environ.get("RUN_ETL_ON_STARTUP"), True)

    # Backup encryption key (optional, derives from SECRET_KEY if not set)
    BACKUP_ENCRYPTION_KEY = os.environ.get("BACKUP_ENCRYPTION_KEY", "")

    # Portfolio forecast: run actual models per product (cached) vs moving average baseline
    PORTFOLIO_RUN_ACTUAL_MODELS = _bool(os.environ.get("PORTFOLIO_RUN_ACTUAL_MODELS"), False)

    @classmethod
    def psycopg2_params(cls) -> dict:
        if cls.DATABASE_URL:
            return {"dsn": cls.DATABASE_URL}
        params = {
            "host": cls.DB_HOST,
            "port": cls.DB_PORT,
            "dbname": cls.DB_NAME,
            "user": cls.DB_USER,
            "password": cls.DB_PASSWORD,
        }
        if cls.DB_SSLMODE:
            params["sslmode"] = cls.DB_SSLMODE
        return params


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = _bool(os.environ.get("SESSION_COOKIE_SECURE"), True)


class TestingConfig(Config):
    TESTING = True
    DEBUG = False
    WTF_CSRF_ENABLED = False
    # Tests stay hermetic: in-memory rate limiting regardless of .env so the
    # suite never depends on a running Redis container.
    RATELIMIT_STORAGE_URI = "memory://"
    # Default to a test-specific DB name to avoid hitting production data
    DB_NAME = os.environ.get("TEST_DB_NAME", "inventory_db_test")


_CONFIGS = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config(name: str | None = None) -> type[Config]:
    """Return the configuration class for the given environment name."""
    env = (name or os.environ.get("FLASK_ENV", "development")).lower()
    if env not in _CONFIGS:
        raise RuntimeError(
            f"Unknown FLASK_ENV '{env}'. Valid values: {', '.join(_CONFIGS.keys())}. "
            f"Set FLASK_ENV explicitly (e.g. 'production', 'development', 'testing')."
        )
    return _CONFIGS[env]
