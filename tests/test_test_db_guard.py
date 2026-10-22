"""Phase 0: conftest must resolve a dedicated ``*_test`` database.

Each test runs ``tests/conftest.py`` in a child interpreter so the guard runs
exactly as it would at pytest import, without ever touching a database.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFTEST = PROJECT_ROOT / "tests" / "conftest.py"
GUARD_MARKER = "dedicated test database"

# Stripped so the parent session's env can't make a case pass for the wrong reason.
_STRIPPED = (
    "TEST_DB_NAME",
    "DB_NAME",
    "DB_HOST",
    "DATABASE_URL",
    "FLASK_ENV",
    "PYTHONPATH",
    "PYTHONHOME",
    "PGHOSTADDR",
    "PGSERVICE",
    "PGSERVICEFILE",
)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Override the root autouse fixture: no app is created in this module."""
    yield


def _run_conftest(prelude: str = "", **extra_env) -> tuple[subprocess.CompletedProcess, list[str]]:
    env = {key: value for key, value in os.environ.items() if key not in _STRIPPED}
    env.update(extra_env)
    code = (
        "import os, runpy; "
        + prelude
        + f"runpy.run_path({str(CONFTEST)!r}); "
        "print('RESOLVED=' + os.environ.get('TEST_DB_NAME','')); "
        "print('DBNAME=' + os.environ.get('DB_NAME','')); "
        "print('DSN_EMPTY=' + str(os.environ.get('DATABASE_URL') == '')); "
        "print('HOST=' + os.environ.get('DB_HOST','')); "
        "print('PGHOSTADDR_ABSENT=' + str('PGHOSTADDR' not in os.environ)); "
        "print('PGSERVICE_ABSENT=' + str('PGSERVICE' not in os.environ))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc, (proc.stdout + proc.stderr).splitlines()


def _assert_guard_error(proc: subprocess.CompletedProcess, lines: list[str]) -> None:
    text = "\n".join(lines)
    assert proc.returncode != 0, "guard did not abort conftest import"
    assert "Refusing to run tests against database" in text
    assert GUARD_MARKER in text


def test_missing_test_db_name_defaults_to_test_db():
    proc, lines = _run_conftest()

    assert proc.returncode == 0, proc.stderr
    assert "RESOLVED=inventory_db_test" in lines
    assert "DBNAME=inventory_db_test" in lines
    assert "DSN_EMPTY=True" in lines
    assert "HOST=localhost" in lines


def test_dev_db_is_rejected():
    proc, lines = _run_conftest(TEST_DB_NAME="inventory_db")

    _assert_guard_error(proc, lines)
    assert "inventory_db" in "\n".join(lines)


@pytest.mark.parametrize("db_name", ["postgres", "template0", "template1"])
def test_system_databases_are_rejected(db_name):
    proc, lines = _run_conftest(TEST_DB_NAME=db_name)

    _assert_guard_error(proc, lines)


def test_custom_test_db_is_accepted():
    proc, lines = _run_conftest(TEST_DB_NAME="inventory_custom_test")

    assert proc.returncode == 0, proc.stderr
    assert "RESOLVED=inventory_custom_test" in lines
    assert "DBNAME=inventory_custom_test" in lines


def test_inherited_remote_dsn_is_cleared():
    proc, lines = _run_conftest(
        DATABASE_URL="postgresql://user:pass@db.example.invalid:5432/inventory_db"
    )

    assert proc.returncode == 0, proc.stderr
    assert "DSN_EMPTY=True" in lines


def test_remote_db_host_is_forced_localhost():
    proc, lines = _run_conftest(DB_HOST="db.example.invalid")

    assert proc.returncode == 0, proc.stderr
    assert "HOST=localhost" in lines


def test_guard_error_never_contains_password():
    sentinel = "sentinel-phase0-do-not-leak"
    proc, lines = _run_conftest(TEST_DB_NAME="inventory_db", DB_PASSWORD=sentinel)

    _assert_guard_error(proc, lines)
    assert sentinel not in "\n".join(lines)


def test_libpq_host_overrides_are_stripped():
    proc, lines = _run_conftest(
        PGHOSTADDR="192.0.2.1",
        PGSERVICE="evil-service",
        PGSERVICEFILE="C:/evil-pg-service.conf",
    )

    assert proc.returncode == 0, proc.stderr
    assert "PGHOSTADDR_ABSENT=True" in lines
    assert "PGSERVICE_ABSENT=True" in lines


def test_libpq_overrides_are_stripped_again_after_app_import():
    # The app package calls load_dotenv(), which can re-add keys from .env.
    prelude = (
        "import dotenv; "
        "dotenv.load_dotenv = lambda *a, **k: "
        "(os.environ.setdefault('PGHOSTADDR', '192.0.2.1'), "
        " os.environ.setdefault('PGSERVICE', 'evil-service'), False)[2]; "
    )
    proc, lines = _run_conftest(prelude=prelude)

    assert proc.returncode == 0, proc.stderr
    assert "PGHOSTADDR_ABSENT=True" in lines
    assert "PGSERVICE_ABSENT=True" in lines
