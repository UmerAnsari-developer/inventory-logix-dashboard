"""Test fixtures for the InventoryLogix application."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Read DB_PASSWORD from .env without polluting os.environ.
# load_dotenv() hasn't run yet when this module is imported, so a plain
# os.environ.get("DB_PASSWORD") can resolve to "" when the shell does not
# export it.  dotenv_values() reads .env in isolation.
_env = dotenv_values(PROJECT_ROOT / ".env")

# Forced (not setdefault): a developer shell or .env pointing at a remote
# database must never leak into a test run.
os.environ["FLASK_ENV"] = "testing"
os.environ["WTF_CSRF_ENABLED"] = "0"
os.environ.setdefault("SECRET_KEY", "test-secret-key")

# Tests always run against the local PostgreSQL, never the Render database
# configured in .env.  load_dotenv() won't override these.
os.environ["DB_HOST"] = "localhost"
os.environ["DB_PORT"] = "5432"
os.environ["DB_USER"] = "postgres"
os.environ["DB_SSLMODE"] = ""
# .env may carry a Render DATABASE_URL; tests use only the local DB_* fields.
os.environ["DATABASE_URL"] = ""
# An explicit non-empty DB_PASSWORD in the environment wins; otherwise use .env's.
os.environ["DB_PASSWORD"] = os.environ.get("DB_PASSWORD") or _env.get("DB_PASSWORD", "")
# Drop libpq overrides so a developer shell cannot redirect host resolution;
# every app connect path passes host/dbname explicitly.
for _libpq in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"):
    os.environ.pop(_libpq, None)

# Tests run against a local, dedicated ``*_test`` database — never the dev DB.
test_db = (os.environ.get("TEST_DB_NAME") or "inventory_db_test").strip()


def _guard_error(detail: str) -> RuntimeError:
    # Never interpolate credentials (or the resolved params) into this message.
    return RuntimeError(
        f"Refusing to run tests against database {test_db!r}: "
        f"tests require a dedicated test database. {detail} "
        "Create it first (for example: createdb inventory_db_test)."
    )


if not test_db.endswith("_test"):
    raise _guard_error(
        "Set TEST_DB_NAME to a local database whose name ends with '_test'."
    )

os.environ["DB_NAME"] = test_db
os.environ["TEST_DB_NAME"] = test_db

# Validate the effective config the app will actually connect with, not just
# the raw environment variables.  Importing app.config executes the app package
# (a few seconds at collection) but creates no Flask app and opens no DB.
from app.config.settings import TestingConfig  # noqa: E402  (after env is forced)

# Importing the app package runs load_dotenv(), which can re-add these keys.
for _libpq in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"):
    os.environ.pop(_libpq, None)

_params = TestingConfig.psycopg2_params()
if (
    "dsn" in _params
    or _params.get("dbname") != test_db
    or _params.get("host") not in {"localhost", "127.0.0.1", "::1"}
):
    raise _guard_error(
        "Resolved database config is not the local test database "
        "(DATABASE_URL must be empty and DB_HOST must be localhost)."
    )


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


@pytest.fixture(autouse=True)
def _reset_rate_limiter(app):
    """Fresh flask-limiter buckets for every test (Issue 04 suite hygiene).

    The app — and the limiter singleton bound to it — are session-scoped, so
    buckets would otherwise leak between tests and make every limit
    assertion order-dependent. Replaces the ad-hoc ``limiter.reset()`` calls
    that used to live in test_auth_lockout.py and test_frontend_mitigations.py.
    Depends on ``app`` so init_app has run before reset() is called.
    """
    from app.extensions import limiter

    def _safe_reset():
        try:
            limiter.reset()
        except AssertionError:
            # flask-limiter's reset() asserts self._storage; a bare test-app
            # fixture (e.g. test_audit_decorator.py) never init_app's the
            # limiter, so there is nothing to reset. Tests relying on real
            # rate-limit buckets are unaffected — reset() works normally
            # whenever the limiter is bound.
            pass

    _safe_reset()
    yield
    _safe_reset()


@pytest.fixture()
def auth_client(client):
    """Returns a logged-in test client."""
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "Admin@123", "remember": "on"},
        follow_redirects=False,
    )
    return client
