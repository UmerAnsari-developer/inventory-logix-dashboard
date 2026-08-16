"""Test fixtures for the InventoryLogix application."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("FLASK_ENV", "testing")
os.environ.setdefault("WTF_CSRF_ENABLED", "0")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

# Tests always run against the local development PostgreSQL, never the
# Render database configured in .env. load_dotenv() won't override these.
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "inventory_db")
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "Um%25ans12er")
os.environ.setdefault("DB_SSLMODE", "")
# .env may carry a Render DATABASE_URL; tests must use the local DB_* fields.
os.environ.setdefault("DATABASE_URL", "")


@pytest.fixture(scope="session")
def app():
    from app import create_app
    flask_app = create_app("testing")
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def runner(app):
    return app.test_cli_runner()


@pytest.fixture()
def auth_client(client):
    """Returns a logged-in test client."""
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "Admin@123", "remember": "on"},
        follow_redirects=False,
    )
    return client
