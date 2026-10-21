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

    # Host-header allowlist (Flask 3.1): rejects forged Host values, which
    # would otherwise poison password-reset links built from request.host_url.
    # Render injects RENDER_EXTERNAL_HOSTNAME; custom domains go in TRUSTED_HOSTS.
    TRUSTED_HOSTS = sorted(
        {"localhost", "127.0.0.1", "testserver"}
        | {
            host.strip()
            for host in os.environ.get("TRUSTED_HOSTS", "").split(",")
            if host.strip()
        }
        | (
            {os.environ["RENDER_EXTERNAL_HOSTNAME"]}
            if os.environ.get("RENDER_EXTERNAL_HOSTNAME")
            else set()
        )
    )

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

    # GAP-009: alert routing channels — all optional; DB-only when unset.
    ALERT_EMAIL_ENABLED = _bool(os.environ.get("ALERT_EMAIL_ENABLED"), False)
    ALERT_EMAIL_RECIPIENTS = os.environ.get("ALERT_EMAIL_RECIPIENTS", "")  # comma-separated
    SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
    ALERT_WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK_URL", "")

    # Rate limiting (flask-limiter) uses its built-in in-process store.
    # The deployment is pinned to a single gunicorn worker (render.yaml
    # --workers 1), so memory:// is exact; the per-account login lockout is
    # persisted in PostgreSQL (auth_service) and holds regardless of workers.
    RATELIMIT_STORAGE_URI = "memory://"
    # Opt-in reverse-proxy trust (Render etc.). When truthy the factory
    # installs ProxyFix so the limiter keys on the X-Forwarded-For client
    # hop instead of the shared proxy IP. Default OFF keeps XFF
    # spoof-proof when the app is directly exposed.
    TRUST_PROXY = _bool(os.environ.get("TRUST_PROXY"))

    # Bootstrap behaviour. ``RUN_ETL_ON_STARTUP`` lets deployments skip the
    # (potentially slow, remote) star-schema rebuild on every boot when the
    # warehouse is already populated. Defaults to True for safety.
    RUN_ETL_ON_STARTUP = _bool(os.environ.get("RUN_ETL_ON_STARTUP"), True)

    # Backup encryption key (optional, derives from SECRET_KEY if not set)
    BACKUP_ENCRYPTION_KEY = os.environ.get("BACKUP_ENCRYPTION_KEY", "")

    # GAP-012 Batch 5: persistent job queue. When True, background routes
    # enqueue instead of spawning threads and an in-process worker executes
    # jobs (or run `python -m app.worker` standalone). Default off = legacy
    # threading behavior, byte-identical.
    JOB_QUEUE_ENABLED = _bool(os.environ.get("JOB_QUEUE_ENABLED"), False)

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
    # Hermetic: the test suite never starts the worker thread or takes the
    # queue code paths unless a test explicitly flips this per-test.
    JOB_QUEUE_ENABLED = False
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
