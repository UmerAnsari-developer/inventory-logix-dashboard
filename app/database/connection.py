"""PostgreSQL connection helpers built on psycopg2.

Provides per-request connection pooling, schema bootstrap, and sample-data
seeding so the rest of the application can treat the database as a black box.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.extras
from flask import current_app, g

LOGGER = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def get_connection():
    """Return a request-scoped psycopg2 connection with RealDictCursor."""
    if "db" not in g:
        params = current_app.config["psycopg2_params"]()
        if "dsn" in params:
            conn = psycopg2.connect(
                params["dsn"], cursor_factory=psycopg2.extras.RealDictCursor
            )
        else:
            conn = psycopg2.connect(
                cursor_factory=psycopg2.extras.RealDictCursor, **params
            )
        g.db = conn
    return g.db


@contextmanager
def get_cursor(commit: bool = False):
    """Context manager yielding a cursor that commits on success."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def close_connection(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_schema() -> None:
    """Apply schema.sql against the configured database."""
    from psycopg2 import sql as pg_sql

    sql_text = SCHEMA_PATH.read_text(encoding="utf-8")
    params = current_app.config["psycopg2_params"]()
    if "dsn" in params:
        conn = psycopg2.connect(
            params["dsn"], cursor_factory=psycopg2.extras.RealDictCursor
        )
    else:
        conn = psycopg2.connect(
            cursor_factory=psycopg2.extras.RealDictCursor, **params
        )
    try:
        with conn.cursor() as cur:
            cur.execute(sql_text)
        conn.commit()
        LOGGER.info("Database schema initialised.")
    finally:
        conn.close()


def seed_database(force: bool = False) -> None:
    """Populate the database with realistic sample data.

    Imports lazily to avoid circular imports.
    """
    from .seed import run_seed

    run_seed(force=force)


def etl_database(force: bool = False) -> dict:
    """Build the star-schema data warehouse from the operational tables."""
    from .etl import run_etl

    return run_etl(force=force)
