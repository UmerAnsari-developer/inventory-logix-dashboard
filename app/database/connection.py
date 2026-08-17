"""PostgreSQL connection helpers built on psycopg2.

Provides per-request connection pooling, schema bootstrap, and sample-data
seeding so the rest of the application can treat the database as a black box.

Connections are drawn from a small :class:`psycopg2.pool.ThreadedConnectionPool`
keyed by the active database configuration. Reusing connections avoids paying
a fresh TCP + TLS handshake on every request — important when the database is
remote (e.g. Render) rather than localhost.
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.extras
import psycopg2.pool
from flask import current_app, g

LOGGER = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# A small per-config pool so requests reuse connections instead of redoing
# the (potentially SSL) handshake for every page load.
_POOLS: dict[str, psycopg2.pool.ThreadedConnectionPool] = {}
_POOL_LOCK = threading.Lock()
_POOL_SIZE = 20


def _pool_key(params: dict) -> str:
    return repr(sorted(params.items()))


def _make_conn(params: dict):
    if "dsn" in params:
        return psycopg2.connect(
            params["dsn"],
            cursor_factory=psycopg2.extras.RealDictCursor,
            connect_timeout=15,
            keepalives=1,
            keepalives_idle=300,
            keepalives_interval=30,
        )
    return psycopg2.connect(
        cursor_factory=psycopg2.extras.RealDictCursor,
        connect_timeout=15,
        keepalives=1,
        keepalives_idle=300,
        keepalives_interval=30,
        **params,
    )


def _get_pool(params: dict):
    key = _pool_key(params)
    with _POOL_LOCK:
        pool = _POOLS.get(key)
        if pool is None:
            pool = psycopg2.pool.ThreadedConnectionPool(1, _POOL_SIZE, **_make_conn_kwargs(params))
            _POOLS[key] = pool
        return pool


def _make_conn_kwargs(params: dict) -> dict:
    """Turn the config params into kwargs suitable for pool construction."""
    if "dsn" in params:
        return {
            "dsn": params["dsn"],
            "cursor_factory": psycopg2.extras.RealDictCursor,
            "connect_timeout": 15,
            "keepalives": 1,
            "keepalives_idle": 300,
            "keepalives_interval": 30,
        }
    kwargs = dict(params)
    kwargs["cursor_factory"] = psycopg2.extras.RealDictCursor
    kwargs["connect_timeout"] = 15
    kwargs["keepalives"] = 1
    kwargs["keepalives_idle"] = 300
    kwargs["keepalives_interval"] = 30
    return kwargs


def get_connection():
    """Return a pooled, request-scoped psycopg2 connection."""
    if "db" not in g:
        params = current_app.config["psycopg2_params"]()
        pool = _get_pool(params)
        g.db = pool.getconn()
        g.db_pool = pool
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
    pool = g.pop("db_pool", None)
    if db is not None:
        try:
            if _exc is not None:
                db.rollback()
            pool.putconn(db)
        except Exception:
            LOGGER.debug("Could not return connection to pool.", exc_info=True)
            try:
                db.close()
            except Exception:
                pass


def init_schema() -> None:
    """Apply schema.sql against the configured database."""
    sql_text = SCHEMA_PATH.read_text(encoding="utf-8")
    params = current_app.config["psycopg2_params"]()
    conn = _make_conn(params)
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


_BOOTSTRAPPED = False
_BOOTSTRAP_LOCK = threading.Lock()


def bootstrap_database() -> None:
    """Run schema init, seed and ETL at most once per process.

    Idempotent guard so repeated ``create_app`` calls (e.g. the Flask debug
    reloader monitor, test fixtures or multiple workers importing ``run.py``)
    do not re-apply the schema and open fresh database connections on every
    boot.
    """
    global _BOOTSTRAPPED
    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAPPED:
            return
        init_schema()
        seed_database()
        if current_app.config.get("RUN_ETL_ON_STARTUP", True):
            etl_database()
        _BOOTSTRAPPED = True
