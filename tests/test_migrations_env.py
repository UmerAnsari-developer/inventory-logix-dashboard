"""Phase 0: Alembic must refuse unsafe migration targets before connecting."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Override the root autouse fixture: no app is created in this module."""
    yield


def _run_alembic(overrides: dict[str, str]) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for key in (
        "ALLOW_REMOTE_MIGRATIONS",
        "PGHOSTADDR",
        "PGSERVICE",
        "PGSERVICEFILE",
        "DATABASE_URL",
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
    ):
        env.pop(key, None)
    env["ALLOW_REMOTE_MIGRATIONS"] = "0"
    env.update(overrides)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _assert_refused(proc: subprocess.CompletedProcess, marker: str) -> None:
    text = proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert marker in text
    assert "secret-value" not in text


def test_remote_database_url_is_refused():
    proc = _run_alembic(
        {
            "DATABASE_URL": (
                "postgresql://user:secret-value@db.example.invalid:5432/inventory_db"
            )
        }
    )

    _assert_refused(proc, "Refusing to run migrations against non-local database host")


@pytest.mark.parametrize(
    "query",
    [
        "host=db.example.invalid",
        "hostaddr=192.0.2.1",
        "service=evil-service",
        "dbname=other_db",
        "port=6543",
    ],
)
def test_target_overriding_query_is_refused(query: str):
    proc = _run_alembic(
        {
            "DATABASE_URL": (
                "postgresql://user:secret-value@localhost:5432/inventory_db"
                f"?{query}"
            )
        }
    )

    _assert_refused(proc, "target-overriding query parameter")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("DB_HOST", "localhost?host=db.example.invalid"),
        ("DB_PORT", "5432?host=db.example.invalid"),
        ("DB_NAME", "inventory_db?host=db.example.invalid"),
    ],
)
def test_db_env_injection_is_refused(key: str, value: str):
    proc = _run_alembic({"DATABASE_URL": "", "DB_NAME": "inventory_db", key: value})

    _assert_refused(proc, "Refusing")


def test_alembic_ini_is_sanitized():
    text = (PROJECT_ROOT / "alembic.ini").read_text(encoding="utf-8")

    assert "driver://user:pass@localhost/dbname" in text
    assert not re.search(r"postgres(?:ql)?://[^:\s]+:[^@\s]+@", text)
