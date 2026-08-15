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
        data={"username": "admin", "password": "Admin@123"},
        follow_redirects=False,
    )
    return client
