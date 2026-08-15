"""Environment-based configuration classes."""
from __future__ import annotations

import os
from datetime import timedelta


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


class Config:
    """Base configuration loaded from environment variables."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool(os.environ.get("SESSION_COOKIE_SECURE"), False)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_DURATION = timedelta(days=7)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    WTF_CSRF_TIME_LIMIT = 60 * 60 * 8
    WTF_CSRF_ENABLED = True

    # Database
    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_PORT = int(os.environ.get("DB_PORT", "5432"))
    DB_NAME = os.environ.get("DB_NAME", "inventory_db")
    DB_USER = os.environ.get("DB_USER", "postgres")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
    DATABASE_URL = os.environ.get("DATABASE_URL")

    # Rate limiting
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_DEFAULT = "200 per minute"

    # SMTP — used to deliver password-reset emails. When no SMTP host is set
    # the reset link is surfaced in the UI instead (development fallback).
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    MAIL_FROM = os.environ.get("MAIL_FROM", "no-reply@inventorylogix.local")
    MAIL_USE_TLS = _bool(os.environ.get("MAIL_USE_TLS"), True)
    PASSWORD_RESET_TTL_MINUTES = int(os.environ.get("PASSWORD_RESET_TTL_MINUTES", "30"))

    # Feature flags
    AI_FORECAST_ENABLED = _bool(os.environ.get("AI_FORECAST_ENABLED"), True)
    ANOMALY_DETECTION_ENABLED = _bool(os.environ.get("ANOMALY_DETECTION_ENABLED"), True)
    DARK_MODE_ENABLED = _bool(os.environ.get("DARK_MODE_ENABLED"), True)

    # Security headers
    SECURITY_HEADERS_ENABLED = _bool(os.environ.get("SECURITY_HEADERS_ENABLED"), True)

    @classmethod
    def psycopg2_params(cls) -> dict:
        if cls.DATABASE_URL:
            return {"dsn": cls.DATABASE_URL}
        return {
            "host": cls.DB_HOST,
            "port": cls.DB_PORT,
            "dbname": cls.DB_NAME,
            "user": cls.DB_USER,
            "password": cls.DB_PASSWORD,
        }


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
    DB_NAME = os.environ.get("TEST_DB_NAME", "inventory_db")


_CONFIGS = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config(name: str | None = None) -> type[Config]:
    """Return the configuration class for the given environment name."""
    env = (name or os.environ.get("FLASK_ENV", "development")).lower()
    return _CONFIGS.get(env, DevelopmentConfig)
